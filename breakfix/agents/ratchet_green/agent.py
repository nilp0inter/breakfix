"""Ratchet Green Phase - Developer agent that implements minimal code to pass tests."""
import os
import subprocess
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
    PreToolUseHookInput,
    HookContext,
)
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

from .coverage import (
    run_pytest_with_coverage,
    check_coverage_intersection,
    save_baseline,
    format_coverage_feedback,
)
from breakfix.artifacts import (
    agent_input_artifact,
    agent_output_artifact,
    agent_iteration_artifact,
)

if TYPE_CHECKING:
    from breakfix.state import UnitWorkItem, TestCase

MAX_RATCHET_GREEN_RETRIES = 5


@dataclass
class RatchetGreenResult:
    """Result from Developer agent implementing code."""
    success: bool
    error: str = ""
    retries: int = 0


@dataclass
class PytestResult:
    """Result from running pytest."""
    success: bool
    output: str = ""


def permission_handler(
    tool_name: str,
    input_data: dict,
    unit_file_path: Path,
    test_file_path: Path,
) -> PermissionResultAllow | PermissionResultDeny:
    """
    Custom permission handler for Developer agent.

    - Can only Write/Edit the unit implementation file
    - Read-only access to rest of project (for context)
    - NO access to the test file (prevents reading the expected behavior)
    - No execution permissions
    """
    print(f"[PERMISSION-GREEN] tool={tool_name} input={input_data}")
    print(f"[PERMISSION-GREEN] unit_file={unit_file_path} test_file={test_file_path}")

    # Block all execution tools
    if tool_name in ("Bash", "BashOutput", "KillBash"):
        result = PermissionResultDeny(
            message="Execution not allowed in Green phase. Only implement code.",
        )
        print(f"[PERMISSION-GREEN] DENY (execution): {result.message}")
        return result

    resolved_test_file = test_file_path.resolve() if test_file_path else None
    resolved_unit_file = unit_file_path.resolve()
    print(f"[PERMISSION-GREEN] resolved_unit_file={resolved_unit_file} resolved_test_file={resolved_test_file}")

    # Block ALL access to test files
    if tool_name in ("Read", "Write", "Edit"):
        file_path = input_data.get("file_path", "")
        if file_path:
            path = Path(file_path).resolve()
            print(f"[PERMISSION-GREEN] Checking test file access: {path} == {resolved_test_file} ? {path == resolved_test_file}")
            # Block access to the specific test file path
            if resolved_test_file and path == resolved_test_file:
                result = PermissionResultDeny(
                    message="Access denied to test file. The Green agent cannot access test code.",
                )
                print(f"[PERMISSION-GREEN] DENY (test file): {result.message}")
                return result

    # For Write/Edit operations, only allow the unit implementation file
    if tool_name in ("Write", "Edit"):
        file_path = input_data.get("file_path", "")
        if not file_path:
            result = PermissionResultDeny(message="No file path provided")
            print(f"[PERMISSION-GREEN] DENY (no path): {result.message}")
            return result

        path = Path(file_path).resolve()
        print(f"[PERMISSION-GREEN] Checking write: {path} == {resolved_unit_file} ? {path == resolved_unit_file}")
        if path != resolved_unit_file:
            result = PermissionResultDeny(
                message=f"Write/Edit only allowed for {unit_file_path.name}. You can only modify the implementation file.",
            )
            print(f"[PERMISSION-GREEN] DENY (not unit file): {result.message}")
            return result

    # Allow Read for any file (except test file blocked above)
    # Allow Glob/Grep for discovery
    result = PermissionResultAllow(updated_input=input_data)
    print(f"[PERMISSION-GREEN] ALLOW")
    return result


DEVELOPER_SYSTEM_PROMPT = """You are a TDD Developer agent. Your ONLY job is to implement the MINIMAL code to make the failing test pass.

RULES:
1. Implement ONLY what is needed to pass the test - nothing more
2. Replace the NotImplementedError stub with working code
3. Keep the implementation as simple as possible
4. Do NOT over-engineer or add extra features
5. Do NOT read or access the test file

STRICT TDD PRINCIPLES:
- Write the simplest code that could possibly work
- Do NOT anticipate future requirements
- If the test expects a specific value, you can return that value directly
- Refactoring comes later, not now

You can read other source files for context (imports, types, dependencies).
After implementing, say "Implementation complete" and stop.
"""


def _log_message(message):
    """Log messages from Claude SDK with detailed output."""
    if isinstance(message, AssistantMessage):
        print("[RATCHET-GREEN] Claude response:")
        for block in message.content:
            if isinstance(block, TextBlock):
                lines = block.text.split('\n')[:8]
                for line in lines:
                    print(f"[RATCHET-GREEN]   {line[:100]}")
                if len(block.text.split('\n')) > 8:
                    print("[RATCHET-GREEN]   ... (more text)")
            elif isinstance(block, ToolUseBlock):
                print(f"[RATCHET-GREEN]   Tool: {block.name}")
                if hasattr(block, "input") and block.input:
                    if "file_path" in block.input:
                        print(f"[RATCHET-GREEN]     file: {block.input['file_path']}")
            else:
                print(f"[RATCHET-GREEN]   {type(block).__name__}")
    elif isinstance(message, UserMessage):
        content_str = str(message.content)[:80]
        print(f"[RATCHET-GREEN] User/Tool result: {content_str}...")
    elif isinstance(message, ResultMessage):
        status = "ERROR" if message.is_error else "COMPLETE"
        print(f"[RATCHET-GREEN] Agent {status}")


def run_pytest(production_dir: Path) -> PytestResult:
    """Run pytest on all tests in production directory."""
    pytest_path = production_dir / ".venv" / "bin" / "pytest"
    tests_dir = production_dir / "tests"

    print(f"[RATCHET-GREEN] Running pytest: {pytest_path} -v {tests_dir}")

    try:
        result = subprocess.run(
            [str(pytest_path), "-v", str(tests_dir)],
            capture_output=True,
            text=True,
            cwd=str(production_dir),
            timeout=120,  # 2 minute timeout
        )

        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr

        status = "PASSED" if result.returncode == 0 else "FAILED"
        print(f"[RATCHET-GREEN] Pytest {status} (return code: {result.returncode})")

        # Show summary of output
        for line in output.split("\n")[-10:]:
            if line.strip():
                print(f"[RATCHET-GREEN]   {line[:100]}")

        return PytestResult(
            success=(result.returncode == 0),
            output=output,
        )
    except subprocess.TimeoutExpired:
        print("[RATCHET-GREEN] Pytest TIMEOUT after 120 seconds")
        return PytestResult(
            success=False,
            output="Pytest timed out after 120 seconds",
        )
    except Exception as e:
        print(f"[RATCHET-GREEN] Pytest ERROR: {e}")
        return PytestResult(
            success=False,
            output=f"Failed to run pytest: {e}",
        )


async def run_ratchet_green(
    unit: "UnitWorkItem",
    test_case: "TestCase",
    test_file_path: str,
    production_dir: Path,
    working_dir: Path,
    initial_failure: str = "",
    max_retries: int = MAX_RATCHET_GREEN_RETRIES,
) -> RatchetGreenResult:
    """
    Run the Developer agent to implement minimal code for a failing test.

    Args:
        unit: The unit being implemented
        test_case: The test case to satisfy
        test_file_path: Path to the test file (to block access)
        production_dir: Path to production/ directory
        working_dir: Project working directory (for coverage baseline storage)
        initial_failure: Pytest output showing the test failure (from Red phase)
        max_retries: Maximum retry attempts

    Returns:
        RatchetGreenResult with success status
    """
    production_dir = Path(production_dir)
    # unit.module_path is relative to production_dir, so we need to make it absolute
    unit_file_path = production_dir / unit.module_path

    # Convert test file path to absolute path
    if "::" in test_file_path:
        # Extract file path from pytest node ID
        test_file = test_file_path.split("::")[0]
    else:
        test_file = test_file_path
    test_file_abs = production_dir / test_file

    # Create PreToolUse hook for permissions
    async def pre_tool_use_hook(
        hook_input: dict,
        tool_use_id: str | None,
        context: HookContext,
    ) -> dict:
        """PreToolUse hook to enforce permissions for Green agent."""
        tool_name = hook_input.get("tool_name", "")
        tool_input = hook_input.get("tool_input", {})
        print(f"[HOOK-GREEN] PreToolUse: tool={tool_name}, input={tool_input}")

        result = permission_handler(tool_name, tool_input, unit_file_path, test_file_abs)

        if isinstance(result, PermissionResultDeny):
            print(f"[HOOK-GREEN] BLOCKING: {result.message}")
            return {
                "continue_": False,
                "decision": "block",
                "reason": result.message,
            }

        print(f"[HOOK-GREEN] ALLOWING")
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
        extra_args={"replay-user-messages": None},  # Required for rewind_files()
        max_turns=20,
    )

    # Set env var for file checkpointing
    os.environ["CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING"] = "1"

    base_prompt = f"""Implement the MINIMAL code to make the failing test pass.

## Unit Information
Name: {unit.name}
File: {unit.module_path}

## Unit Description (from Oracle)
{unit.description}

## Test Case Specification
{test_case.description}

## Current Test Failure
The test is currently failing with this output:
```
{initial_failure}
```

## Instructions
1. Read the current implementation file at {unit.module_path} to see the stubbed function
2. Replace the NotImplementedError with working code
3. Implement ONLY what is needed to make the test pass
4. Keep it simple - do not over-engineer

CRITICAL:
- You can ONLY edit {unit.module_path}
- Do NOT try to read or access any test files
- Write the simplest code that could possibly work

CRITICAL: DO NOT RUN THE TESTS. I, THE USER, WILL RUN THEM FOR YOU AND PASTE THE OUTPUT.
"""

    retries = 0
    checkpoint_id = None
    start_time = time.time()
    task_id = f"{unit.name}-{test_case.id}"

    print("[RATCHET-GREEN] ========================================")
    print(f"[RATCHET-GREEN] Starting GREEN phase for: {unit.name}")
    print(f"[RATCHET-GREEN] Test case: {test_case.description[:60]}...")
    print(f"[RATCHET-GREEN] Unit file: {unit.module_path}")
    print("[RATCHET-GREEN] ========================================")

    # Create input artifact
    await agent_input_artifact(
        agent_name="ratchet-green",
        prompt=base_prompt,
        context={
            "unit_name": unit.name,
            "test_case_id": test_case.id,
            "unit_file": unit.module_path,
        },
        task_id=task_id,
    )

    try:
        async with ClaudeSDKClient(options=options) as client:
            print(f"[RATCHET-GREEN] Sending initial prompt to developer agent...")
            await client.query(base_prompt)

            while retries < max_retries:
                # Process agent response
                print(f"[RATCHET-GREEN] Waiting for Claude response...")
                async for message in client.receive_response():
                    _log_message(message)
                    if isinstance(message, UserMessage) and hasattr(message, 'uuid') and message.uuid and not checkpoint_id:
                        checkpoint_id = message.uuid
                        print(f"[RATCHET-GREEN] Captured checkpoint: {checkpoint_id[:20]}...")
                    if isinstance(message, ResultMessage):
                        if message.is_error:
                            raise Exception(message.result or "Agent error")

                # Run pytest to verify implementation
                print(f"[RATCHET-GREEN] ----------------------------------------")
                print(f"[RATCHET-GREEN] Running pytest (attempt {retries + 1}/{max_retries})")

                await agent_iteration_artifact(
                    agent_name="ratchet-green",
                    iteration=retries + 1,
                    max_iterations=max_retries,
                    status="running_tests",
                    details="Running pytest to verify implementation",
                    task_id=task_id,
                )

                pytest_result = run_pytest(production_dir)

                if pytest_result.success:
                    print(f"[RATCHET-GREEN] All tests PASSED! Checking coverage...")

                    # Run pytest with coverage to check for dead code
                    cov_success, coverage_data, cov_output = run_pytest_with_coverage(
                        production_dir,
                        unit.module_path,
                    )

                    if coverage_data is None:
                        # Coverage collection failed - abort
                        print("[RATCHET-GREEN] ERROR: Coverage check failed - no coverage data")
                        duration = time.time() - start_time
                        await agent_output_artifact(
                            agent_name="ratchet-green",
                            result=f"Coverage data could not be collected. Output:\n{cov_output[:500]}",
                            success=False,
                            duration_seconds=duration,
                            task_id=task_id,
                        )
                        return RatchetGreenResult(
                            success=False,
                            error=f"Coverage data could not be collected. Output:\n{cov_output[:500]}",
                            retries=retries,
                        )

                    dead_code_lines = check_coverage_intersection(
                        coverage_data,
                        unit.module_path,
                        unit.line_number,
                        unit.end_line_number,
                    )

                    if not dead_code_lines:
                        # Coverage check passed!
                        print("[RATCHET-GREEN] SUCCESS: Coverage check passed!")
                        save_baseline(
                            working_dir,
                            unit.name,
                            coverage_data,
                            unit.module_path,
                            unit.line_number,
                            unit.end_line_number,
                        )
                        duration = time.time() - start_time
                        await agent_output_artifact(
                            agent_name="ratchet-green",
                            result=f"Implementation complete. All tests passing with full coverage.",
                            success=True,
                            duration_seconds=duration,
                            task_id=task_id,
                        )
                        return RatchetGreenResult(success=True, retries=retries)

                    # Coverage violation - need to fix dead code
                    print(f"[RATCHET-GREEN] WARNING: Dead code detected on lines: {dead_code_lines}")
                    retries += 1

                    if retries < max_retries:
                        coverage_feedback = format_coverage_feedback(
                            dead_code_lines,
                            unit.module_path,
                            production_dir,
                        )
                        print("[RATCHET-GREEN] Sending coverage feedback to agent...")
                        await client.query(coverage_feedback)
                        continue  # Agent will fix, then we re-run tests AND coverage
                    else:
                        # Max retries exceeded - rewind and fail
                        print(f"[RATCHET-GREEN] ERROR: Max retries exceeded (dead code)")
                        if checkpoint_id:
                            print(f"[RATCHET-GREEN] Rewinding to checkpoint...")
                            await client.rewind_files(checkpoint_id)

                        duration = time.time() - start_time
                        await agent_output_artifact(
                            agent_name="ratchet-green",
                            result=f"Dead code on lines {dead_code_lines} after {retries} attempts",
                            success=False,
                            duration_seconds=duration,
                            task_id=task_id,
                        )
                        return RatchetGreenResult(
                            success=False,
                            error=f"Dead code on lines {dead_code_lines} after {retries} attempts",
                            retries=retries,
                        )

                # Tests failed - send output back to agent
                retries += 1
                print(f"[RATCHET-GREEN] Tests FAILED (attempt {retries}/{max_retries})")

                await agent_iteration_artifact(
                    agent_name="ratchet-green",
                    iteration=retries,
                    max_iterations=max_retries,
                    status="test_failed",
                    details=pytest_result.output[:500],
                    task_id=task_id,
                )

                if retries < max_retries:
                    # Feed pytest output back to agent
                    feedback_prompt = f"""Tests failed. Please fix the implementation.

## Pytest Output
```
{pytest_result.output}
```

Read the error carefully and fix the code to make all tests pass.
Remember: You can ONLY edit {unit.module_path}
"""
                    print(f"[RATCHET-GREEN] Sending failure feedback to agent...")
                    await client.query(feedback_prompt)
                else:
                    # Max retries exceeded - rewind and fail
                    print(f"[RATCHET-GREEN] ERROR: Max retries exceeded")
                    if checkpoint_id:
                        print(f"[RATCHET-GREEN] Rewinding to checkpoint...")
                        await client.rewind_files(checkpoint_id)

                    duration = time.time() - start_time
                    await agent_output_artifact(
                        agent_name="ratchet-green",
                        result=f"Tests still failing after {retries} attempts. Last output:\n{pytest_result.output[:500]}",
                        success=False,
                        duration_seconds=duration,
                        task_id=task_id,
                    )
                    return RatchetGreenResult(
                        success=False,
                        error=f"Tests still failing after {retries} attempts. Last output:\n{pytest_result.output[:500]}",
                        retries=retries,
                    )

            duration = time.time() - start_time
            await agent_output_artifact(
                agent_name="ratchet-green",
                result="Max retries exceeded",
                success=False,
                duration_seconds=duration,
                task_id=task_id,
            )
            return RatchetGreenResult(
                success=False,
                error="Max retries exceeded",
                retries=retries,
            )

    except Exception as e:
        print(f"[RATCHET-GREEN] FATAL ERROR: {e}")
        duration = time.time() - start_time
        await agent_output_artifact(
            agent_name="ratchet-green",
            result=f"Fatal error: {e}",
            success=False,
            duration_seconds=duration,
            task_id=task_id,
        )
        return RatchetGreenResult(
            success=False,
            error=str(e),
            retries=retries,
        )
