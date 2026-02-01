"""Ratchet Green Phase - Developer agent that implements minimal code to pass tests."""
import logging
import os
import subprocess
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

if TYPE_CHECKING:
    from breakfix.nodes import UnitWorkItem, TestCase


logger = logging.getLogger(__name__)

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
    """Log messages from Claude SDK."""
    if isinstance(message, AssistantMessage):
        logger.info("[DEVELOPER] Assistant message:")
        for block in message.content:
            if isinstance(block, TextBlock):
                for line in block.text.split('\n')[:10]:  # First 10 lines
                    logger.info(f"  {line}")
                if len(block.text.split('\n')) > 10:
                    logger.info("  ...")
            else:
                logger.info(f"  {type(block).__name__}")
    elif isinstance(message, UserMessage):
        logger.info(f"[DEVELOPER] User message: {str(message.content)[:100]}...")
    elif isinstance(message, ResultMessage):
        logger.info(f"[DEVELOPER] Result: is_error={message.is_error}")


def run_pytest(production_dir: Path) -> PytestResult:
    """Run pytest on all tests in production directory."""
    pytest_path = production_dir / ".venv" / "bin" / "pytest"
    tests_dir = production_dir / "tests"

    logger.info(f"[RATCHET-GREEN] Running pytest: {pytest_path} -v {tests_dir}")

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

        logger.info(f"[RATCHET-GREEN] Pytest return code: {result.returncode}")

        return PytestResult(
            success=(result.returncode == 0),
            output=output,
        )
    except subprocess.TimeoutExpired:
        return PytestResult(
            success=False,
            output="Pytest timed out after 120 seconds",
        )
    except Exception as e:
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

    try:
        async with ClaudeSDKClient(options=options) as client:
            logger.info(f"[RATCHET-GREEN] Sending initial prompt to developer agent")
            await client.query(base_prompt)

            while retries < max_retries:
                # Process agent response
                async for message in client.receive_response():
                    _log_message(message)
                    if isinstance(message, UserMessage) and hasattr(message, 'uuid') and message.uuid and not checkpoint_id:
                        checkpoint_id = message.uuid
                        logger.info(f"[RATCHET-GREEN] Captured checkpoint: {checkpoint_id}")
                    if isinstance(message, ResultMessage):
                        if message.is_error:
                            raise Exception(message.result or "Agent error")

                # Run pytest to verify implementation
                logger.info(f"[RATCHET-GREEN] Running pytest (attempt {retries + 1}/{max_retries})")
                pytest_result = run_pytest(production_dir)

                if pytest_result.success:
                    logger.info(f"[RATCHET-GREEN] All tests passed! Checking coverage...")

                    # Run pytest with coverage to check for dead code
                    cov_success, coverage_data, cov_output = run_pytest_with_coverage(
                        production_dir,
                        unit.module_path,
                    )

                    if coverage_data is None:
                        # Coverage collection failed - abort
                        logger.error("[RATCHET-GREEN] Coverage check failed: no coverage data")
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
                        logger.info("[RATCHET-GREEN] Coverage check passed!")
                        save_baseline(
                            working_dir,
                            unit.name,
                            coverage_data,
                            unit.module_path,
                            unit.line_number,
                            unit.end_line_number,
                        )
                        return RatchetGreenResult(success=True, retries=retries)

                    # Coverage violation - need to fix dead code
                    logger.warning(f"[RATCHET-GREEN] Dead code detected on lines: {dead_code_lines}")
                    retries += 1

                    if retries < max_retries:
                        coverage_feedback = format_coverage_feedback(
                            dead_code_lines,
                            unit.module_path,
                            production_dir,
                        )
                        logger.info("[RATCHET-GREEN] Sending coverage feedback to agent")
                        await client.query(coverage_feedback)
                        continue  # Agent will fix, then we re-run tests AND coverage
                    else:
                        # Max retries exceeded - rewind and fail
                        logger.error(f"[RATCHET-GREEN] Max retries exceeded (dead code)")
                        if checkpoint_id:
                            logger.info(f"[RATCHET-GREEN] Rewinding to checkpoint {checkpoint_id}")
                            await client.rewind_files(checkpoint_id)

                        return RatchetGreenResult(
                            success=False,
                            error=f"Dead code on lines {dead_code_lines} after {retries} attempts",
                            retries=retries,
                        )

                # Tests failed - send output back to agent
                retries += 1
                logger.warning(f"[RATCHET-GREEN] Tests failed (attempt {retries}/{max_retries})")

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
                    logger.info(f"[RATCHET-GREEN] Sending failure feedback to agent")
                    await client.query(feedback_prompt)
                else:
                    # Max retries exceeded - rewind and fail
                    logger.error(f"[RATCHET-GREEN] Max retries exceeded")
                    if checkpoint_id:
                        logger.info(f"[RATCHET-GREEN] Rewinding to checkpoint {checkpoint_id}")
                        await client.rewind_files(checkpoint_id)

                    return RatchetGreenResult(
                        success=False,
                        error=f"Tests still failing after {retries} attempts. Last output:\n{pytest_result.output[:500]}",
                        retries=retries,
                    )

            return RatchetGreenResult(
                success=False,
                error="Max retries exceeded",
                retries=retries,
            )

    except Exception as e:
        logger.error(f"[RATCHET-GREEN] Fatal error: {e}")
        return RatchetGreenResult(
            success=False,
            error=str(e),
            retries=retries,
        )
