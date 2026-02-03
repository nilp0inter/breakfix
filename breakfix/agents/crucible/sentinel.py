"""Sentinel agent that writes tests to kill surviving mutants."""

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    ResultMessage,
    AssistantMessage,
    UserMessage,
    TextBlock,
    ToolUseBlock,
    HookMatcher,
    HookContext,
)
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

from breakfix.artifacts import agent_input_artifact, agent_output_artifact

if TYPE_CHECKING:
    from breakfix.state import UnitWorkItem
    from .mutation import SurvivingMutant

MAX_SENTINEL_RETRIES = 3


@dataclass
class SentinelResult:
    """Result from Sentinel agent writing a mutant-killing test."""
    success: bool
    test_file_path: str = ""
    error: str = ""
    retries: int = 0


def permission_handler(
    tool_name: str,
    input_data: dict,
    test_file_path: Path,
    production_dir: Path,
) -> PermissionResultAllow | PermissionResultDeny:
    """
    Custom permission handler for Sentinel agent.

    - Read: All files (implementation + tests)
    - Write/Edit: Only the unit's test file
    - Execution: Blocked (system runs tests externally)
    """
    print(f"[PERMISSION-SENTINEL] tool={tool_name} input={input_data}")
    print(f"[PERMISSION-SENTINEL] test_file={test_file_path}")

    # Block all execution tools
    if tool_name in ("Bash", "BashOutput", "KillBash"):
        result = PermissionResultDeny(
            message="Execution not allowed. Only write tests, do not run them.",
        )
        print(f"[PERMISSION-SENTINEL] DENY (execution): {result.message}")
        return result

    # For write operations, only allow the specific test file
    if tool_name in ("Write", "Edit"):
        file_path = input_data.get("file_path", "")
        if not file_path:
            result = PermissionResultDeny(message="No file path provided")
            print(f"[PERMISSION-SENTINEL] DENY (no path): {result.message}")
            return result

        path = Path(file_path).resolve()
        test_file_resolved = test_file_path.resolve()

        print(f"[PERMISSION-SENTINEL] Checking write: {path} == {test_file_resolved} ? {path == test_file_resolved}")

        if path != test_file_resolved:
            result = PermissionResultDeny(
                message=f"Can only write to {test_file_path}. "
                        f"You cannot modify other files.",
            )
            print(f"[PERMISSION-SENTINEL] DENY (wrong file): {result.message}")
            return result

    # Allow Read for all files
    # Allow Glob for file discovery
    # Allow Grep for searching
    result = PermissionResultAllow(updated_input=input_data)
    print(f"[PERMISSION-SENTINEL] ALLOW")
    return result


SENTINEL_SYSTEM_PROMPT = """You are a Sentinel agent for mutation testing. A mutant has survived - this means your test suite didn't catch a code change.

Your job is to write ONE new test that:
1. PASSES on the original (correct) code
2. FAILS on the mutated (incorrect) code

RULES:
1. Write EXACTLY ONE test function - no more, no less
2. Add the test to the EXISTING test file (do not create new files)
3. The test should specifically target the behavior change shown in the mutant diff
4. Use pytest style tests (def test_...)
5. Name the test descriptively based on what behavior it verifies

DO NOT:
- Write more than one test function
- Create new test files
- Modify implementation code
- Run any commands or tests

After writing the test, say "Test written" and stop.
"""


def _log_message(message):
    """Log messages from Claude SDK with detailed output."""
    if isinstance(message, AssistantMessage):
        print("[SENTINEL] Claude response:")
        for block in message.content:
            if isinstance(block, TextBlock):
                lines = block.text.split('\n')[:8]
                for line in lines:
                    print(f"[SENTINEL]   {line[:100]}")
                if len(block.text.split('\n')) > 8:
                    print("[SENTINEL]   ... (more text)")
            elif isinstance(block, ToolUseBlock):
                print(f"[SENTINEL]   Tool: {block.name}")
                if hasattr(block, "input") and block.input:
                    if "file_path" in block.input:
                        print(f"[SENTINEL]     file: {block.input['file_path']}")
            else:
                print(f"[SENTINEL]   {type(block).__name__}")
    elif isinstance(message, UserMessage):
        content_str = str(message.content)[:80]
        print(f"[SENTINEL] User/Tool result: {content_str}...")
    elif isinstance(message, ResultMessage):
        status = "ERROR" if message.is_error else "COMPLETE"
        print(f"[SENTINEL] Agent {status}")


def _calculate_test_file_path(unit_name: str) -> str:
    """
    Calculate the test file path from unit name.

    Pattern: tests/unit/<all_parts_except_last>/test_<last_part>.py

    Example: "thedump.idea_capture.core._cleanup_temp_file"
             -> "tests/unit/thedump/idea_capture/core/test__cleanup_temp_file.py"
    """
    parts = unit_name.split(".")
    if len(parts) < 2:
        return f"tests/unit/test_{parts[0]}.py"

    path_parts = parts[:-1]
    unit = parts[-1]

    path = "/".join(path_parts)
    return f"tests/unit/{path}/test_{unit}.py"


async def run_sentinel(
    unit: "UnitWorkItem",
    mutant: "SurvivingMutant",
    production_dir: Path,
    max_retries: int = MAX_SENTINEL_RETRIES,
) -> SentinelResult:
    """
    Run the Sentinel agent to write a test that kills a mutant.

    Args:
        unit: The unit being tested
        mutant: The surviving mutant to kill
        production_dir: Path to production/ directory
        max_retries: Maximum retry attempts

    Returns:
        SentinelResult with success status and test file path
    """
    production_dir = Path(production_dir)
    start_time = time.time()
    task_id = f"{unit.name}-mutant-{mutant.id}"

    # Calculate test file path
    test_file_path = _calculate_test_file_path(unit.name)
    test_file_abs = production_dir / test_file_path

    print("[SENTINEL] ========================================")
    print(f"[SENTINEL] Targeting mutant {mutant.id}")
    print(f"[SENTINEL] Unit: {unit.name}")
    print(f"[SENTINEL] Test file: {test_file_path}")
    print("[SENTINEL] ========================================")

    # Ensure test file exists (it should from Ratchet phase)
    if not test_file_abs.exists():
        print(f"[SENTINEL] ERROR: Test file does not exist: {test_file_path}")
        return SentinelResult(
            success=False,
            error=f"Test file does not exist: {test_file_path}. "
                  f"The Ratchet phase should have created it.",
        )

    # Read existing test file content
    existing_tests = test_file_abs.read_text()

    # Create permission handler hook
    async def pre_tool_use_hook(
        hook_input: dict,
        tool_use_id: str | None,
        context: HookContext,
    ) -> dict:
        """PreToolUse hook to enforce permissions for Sentinel agent."""
        tool_name = hook_input.get("tool_name", "")
        tool_input = hook_input.get("tool_input", {})
        print(f"[HOOK-SENTINEL] PreToolUse: tool={tool_name}")

        result = permission_handler(tool_name, tool_input, test_file_abs, production_dir)

        if isinstance(result, PermissionResultDeny):
            print(f"[HOOK-SENTINEL] BLOCKING: {result.message}")
            return {
                "continue_": False,
                "decision": "block",
                "reason": result.message,
            }

        print(f"[HOOK-SENTINEL] ALLOWING")
        return {"continue_": True}

    # Create hook matcher for all tools
    hook_matchers = [
        HookMatcher(
            matcher=None,  # Match all tools
            hooks=[pre_tool_use_hook],
            timeout=60.0,
        )
    ]

    options = ClaudeAgentOptions(
        cwd=str(production_dir),
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
        hooks={"PreToolUse": hook_matchers},
        permission_mode="acceptEdits",
        enable_file_checkpointing=True,
        extra_args={"replay-user-messages": None},
        max_turns=15,
    )

    # Set env var for file checkpointing
    os.environ["CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING"] = "1"

    base_prompt = f"""A mutant has survived mutation testing. Write a test to kill it.

## Surviving Mutant (ID: {mutant.id})
The following diff shows what the mutant changed:

```diff
{mutant.diff}
```

## Unit Under Test
Name: {unit.name}
Module: {unit.module_path}

Description:
{unit.description}

## Current Code
```python
{unit.code}
```

## Existing Tests
The test file is at: {test_file_path}

Current contents:
```python
{existing_tests}
```

## Instructions
1. Analyze the mutant diff to understand what behavior change it introduces
2. Write ONE new test function that:
   - PASSES when run against the original code shown above
   - FAILS when run against the mutated version
3. Add the test to the existing test file (edit, don't create new)
4. Name the test descriptively (e.g., test_<function>_<specific_behavior>)

The test should target the SPECIFIC change in the mutant diff.
For example, if the mutant changes `>` to `>=`, test boundary conditions.

CRITICAL: DO NOT RUN THE TESTS. I, THE USER, WILL RUN THEM FOR YOU.
"""

    retries = 0
    prompt = base_prompt

    # Create input artifact
    await agent_input_artifact(
        agent_name="sentinel",
        prompt=base_prompt,
        context={
            "unit_name": unit.name,
            "mutant_id": mutant.id,
            "test_file": test_file_path,
        },
        task_id=task_id,
    )

    try:
        async with ClaudeSDKClient(options=options) as client:
            while retries < max_retries:
                checkpoint_id = None

                try:
                    print(f"[SENTINEL] ----------------------------------------")
                    print(f"[SENTINEL] Attempt {retries + 1}/{max_retries}")
                    print(f"[SENTINEL] Sending prompt...")
                    await client.query(prompt)

                    # Process response and capture checkpoint
                    print("[SENTINEL] Waiting for Claude response...")
                    async for message in client.receive_response():
                        _log_message(message)
                        if isinstance(message, UserMessage) and hasattr(message, 'uuid') and message.uuid and not checkpoint_id:
                            checkpoint_id = message.uuid
                            print(f"[SENTINEL] Captured checkpoint: {checkpoint_id[:20]}...")
                        if isinstance(message, ResultMessage):
                            if message.is_error:
                                raise Exception(message.result or "Agent error")

                    # Verify test file was modified
                    new_content = test_file_abs.read_text()
                    if new_content == existing_tests:
                        error_msg = "Test file was not modified. Please add a new test."
                        print(f"[SENTINEL] WARNING: {error_msg}")

                        if checkpoint_id:
                            await client.rewind_files(checkpoint_id)

                        retries += 1
                        if retries < max_retries:
                            prompt = f"{base_prompt}\n\nPREVIOUS ATTEMPT FAILED: {error_msg}"
                            continue

                        duration = time.time() - start_time
                        await agent_output_artifact(
                            agent_name="sentinel",
                            result=error_msg,
                            success=False,
                            duration_seconds=duration,
                            task_id=task_id,
                        )
                        return SentinelResult(
                            success=False,
                            error=error_msg,
                            retries=retries,
                        )

                    # Count new test functions added
                    import re
                    old_tests = set(re.findall(r'def (test_\w+)\(', existing_tests))
                    new_tests = set(re.findall(r'def (test_\w+)\(', new_content))
                    added_tests = new_tests - old_tests

                    if len(added_tests) == 0:
                        error_msg = "No new test function was added."
                        print(f"[SENTINEL] WARNING: {error_msg}")

                        if checkpoint_id:
                            await client.rewind_files(checkpoint_id)

                        retries += 1
                        if retries < max_retries:
                            prompt = f"{base_prompt}\n\nPREVIOUS ATTEMPT FAILED: {error_msg}"
                            continue

                        duration = time.time() - start_time
                        await agent_output_artifact(
                            agent_name="sentinel",
                            result=error_msg,
                            success=False,
                            duration_seconds=duration,
                            task_id=task_id,
                        )
                        return SentinelResult(
                            success=False,
                            error=error_msg,
                            retries=retries,
                        )

                    if len(added_tests) > 1:
                        print(f"[SENTINEL] Note: Multiple tests added: {added_tests}. Keeping them all.")

                    print(f"[SENTINEL] SUCCESS: New test(s) added: {added_tests}")

                    # Update existing_tests for next iteration if needed
                    existing_tests = new_content

                    duration = time.time() - start_time
                    await agent_output_artifact(
                        agent_name="sentinel",
                        result=f"Added test(s) to kill mutant {mutant.id}: {added_tests}",
                        success=True,
                        duration_seconds=duration,
                        task_id=task_id,
                    )
                    return SentinelResult(
                        success=True,
                        test_file_path=test_file_path,
                        retries=retries,
                    )

                except Exception as e:
                    print(f"[SENTINEL] ERROR: {e}")
                    retries += 1
                    if retries >= max_retries:
                        duration = time.time() - start_time
                        await agent_output_artifact(
                            agent_name="sentinel",
                            result=str(e),
                            success=False,
                            duration_seconds=duration,
                            task_id=task_id,
                        )
                        return SentinelResult(
                            success=False,
                            error=str(e),
                            retries=retries,
                        )
                    prompt = f"{base_prompt}\n\nPREVIOUS ATTEMPT ERROR: {e}\nPlease try again."

            duration = time.time() - start_time
            await agent_output_artifact(
                agent_name="sentinel",
                result="Max retries exceeded",
                success=False,
                duration_seconds=duration,
                task_id=task_id,
            )
            return SentinelResult(
                success=False,
                error="Max retries exceeded",
                retries=retries,
            )

    except Exception as e:
        print(f"[SENTINEL] FATAL ERROR: {e}")
        duration = time.time() - start_time
        await agent_output_artifact(
            agent_name="sentinel",
            result=f"Fatal error: {e}",
            success=False,
            duration_seconds=duration,
            task_id=task_id,
        )
        return SentinelResult(
            success=False,
            error=str(e),
            retries=retries,
        )
