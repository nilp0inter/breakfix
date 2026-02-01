"""Ratchet Red Phase - Tester agent that writes exactly ONE failing test."""
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Set

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

from .validator import validate_test
from .arbiter import arbitrate_test

if TYPE_CHECKING:
    from breakfix.nodes import UnitWorkItem, TestCase


logger = logging.getLogger(__name__)

MAX_RATCHET_RED_RETRIES = 3


@dataclass
class RatchetRedResult:
    """Result from Tester agent writing a failing test."""
    success: bool
    test_file_path: str = ""
    error: str = ""
    retries: int = 0
    pytest_failure: str = ""  # Output from running pytest (test should fail)
    skipped_green: bool = False  # True if test was kept by arbiter but Green phase should be skipped


@dataclass
class PytestResult:
    """Result from running pytest."""
    success: bool
    output: str = ""


def run_pytest(production_dir: Path, test_file: str) -> PytestResult:
    """Run pytest on the specific test file to verify it fails."""
    pytest_path = production_dir / ".venv" / "bin" / "pytest"

    logger.info(f"[RATCHET-RED] Running pytest: {pytest_path} -v {test_file}")

    try:
        result = subprocess.run(
            [str(pytest_path), "-v", test_file],
            capture_output=True,
            text=True,
            cwd=str(production_dir),
            timeout=120,
        )

        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr

        logger.info(f"[RATCHET-RED] Pytest return code: {result.returncode}")

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


def permission_handler(
    tool_name: str,
    input_data: dict,
    tests_dir: Path,
    unit_file_path: Path,
) -> PermissionResultAllow | PermissionResultDeny:
    """
    Custom permission handler for Tester agent.

    - Full Read/Write/Edit permissions on tests/ directory
    - Read-only access to rest of project (EXCEPT the unit implementation file)
    - NO access to unit implementation file (reserved for Green agent)
    - No execution permissions
    """
    print(f"[PERMISSION-RED] tool={tool_name} input={input_data}")
    print(f"[PERMISSION-RED] tests_dir={tests_dir} unit_file={unit_file_path}")

    # Block all execution tools
    if tool_name in ("Bash", "BashOutput", "KillBash"):
        result = PermissionResultDeny(
            message="Execution not allowed in Red phase. Only write tests, do not run them.",
        )
        print(f"[PERMISSION-RED] DENY (execution): {result.message}")
        return result

    resolved_unit_file = unit_file_path.resolve()
    print(f"[PERMISSION-RED] resolved_unit_file={resolved_unit_file}")

    # Block ALL access to the unit implementation file
    if tool_name in ("Read", "Write", "Edit"):
        file_path = input_data.get("file_path", "")
        if file_path:
            path = Path(file_path).resolve()
            print(f"[PERMISSION-RED] Checking file access: {path} == {resolved_unit_file} ? {path == resolved_unit_file}")
            if path == resolved_unit_file:
                result = PermissionResultDeny(
                    message=f"Access denied to {unit_file_path.name}. The Red agent cannot access the implementation file.",
                )
                print(f"[PERMISSION-RED] DENY (unit file): {result.message}")
                return result

    # Block Grep from searching in the unit implementation file
    if tool_name == "Grep":
        grep_path = input_data.get("path", "")
        if grep_path:
            path = Path(grep_path).resolve()
            print(f"[PERMISSION-RED] Checking grep path: {path} == {resolved_unit_file} ? {path == resolved_unit_file}")
            # Block if grepping the exact file
            if path == resolved_unit_file:
                result = PermissionResultDeny(
                    message=f"Cannot search in {unit_file_path.name}. The Red agent cannot access the implementation file.",
                )
                print(f"[PERMISSION-RED] DENY (grep unit file): {result.message}")
                return result

    # For file write operations, only allow in tests/ directory
    if tool_name in ("Write", "Edit"):
        file_path = input_data.get("file_path", "")
        if not file_path:
            result = PermissionResultDeny(message="No file path provided")
            print(f"[PERMISSION-RED] DENY (no path): {result.message}")
            return result

        path = Path(file_path).resolve()
        tests_dir_resolved = tests_dir.resolve()
        print(f"[PERMISSION-RED] Checking write: {path} starts with {tests_dir_resolved} ? {str(path).startswith(str(tests_dir_resolved))}")
        if not str(path).startswith(str(tests_dir_resolved)):
            result = PermissionResultDeny(
                message=f"Write/Edit only allowed in {tests_dir}. You can only modify test files.",
            )
            print(f"[PERMISSION-RED] DENY (outside tests): {result.message}")
            return result

    # Allow Read for any file (except unit file blocked above)
    # Allow Glob for discovery (file names only, not contents)
    # Allow Grep for other files (blocked above for unit file)
    result = PermissionResultAllow(updated_input=input_data)
    print(f"[PERMISSION-RED] ALLOW")
    return result


TESTER_SYSTEM_PROMPT = """You are a TDD Tester agent. Your ONLY job is to write exactly ONE failing test.

RULES:
1. Write EXACTLY ONE test function/method - no more, no less
2. The test MUST fail against the current implementation
3. Put the test in the tests/ directory
4. Follow existing test patterns in the project if any exist
5. The test should verify the behavior described in the test case specification
6. Use pytest style tests (def test_... or class Test...)

DO NOT:
- Write more than one test function
- Write implementation code
- Modify any source files outside tests/
- Run any commands or tests
- Create multiple test files for one test case
- Read or access implementation source files (src/)

After writing the test, say "Test written" and stop.
"""


def _log_message(message):
    """Log messages from Claude SDK."""
    if isinstance(message, AssistantMessage):
        logger.info("[TESTER] Assistant message:")
        for block in message.content:
            if isinstance(block, TextBlock):
                for line in block.text.split('\n')[:10]:  # First 10 lines
                    logger.info(f"  {line}")
                if len(block.text.split('\n')) > 10:
                    logger.info("  ...")
            else:
                logger.info(f"  {type(block).__name__}")
    elif isinstance(message, UserMessage):
        logger.info(f"[TESTER] User message: {str(message.content)[:100]}...")
    elif isinstance(message, ResultMessage):
        logger.info(f"[TESTER] Result: is_error={message.is_error}")


def _extract_signature(code: str) -> str:
    """
    Extract just the function/class signature from code.

    Extracts the def/class line, parameters, and docstring (if present),
    but NOT the implementation body. This prevents leaking prototype code.
    """
    lines = code.strip().split('\n')
    if not lines:
        return ""

    result_lines = []
    in_docstring = False
    docstring_quote = None

    for i, line in enumerate(lines):
        stripped = line.strip()

        # First line should be def/class/async def
        if i == 0:
            result_lines.append(line)
            # Check if it's a one-liner (has : and body on same line)
            if ':' in line and not stripped.endswith(':'):
                # One-liner function, just show the signature part
                colon_idx = line.index(':')
                result_lines[0] = line[:colon_idx + 1]
                result_lines.append("    ...")
                break
            continue

        # Check for docstring start
        if not in_docstring and (stripped.startswith('"""') or stripped.startswith("'''")):
            docstring_quote = stripped[:3]
            result_lines.append(line)
            # Check if docstring ends on same line
            if stripped.count(docstring_quote) >= 2 and len(stripped) > 3:
                in_docstring = False
            else:
                in_docstring = True
            continue

        # Inside docstring
        if in_docstring:
            result_lines.append(line)
            if docstring_quote in stripped:
                in_docstring = False
            continue

        # After docstring (or if no docstring), add placeholder and stop
        result_lines.append("    ...")
        break

    return '\n'.join(result_lines)


def _calculate_test_file_path(unit_name: str) -> str:
    """
    Calculate the test file path from unit name.

    Pattern: tests/unit/<all_parts_except_last>/test_<last_part>.py

    Example: "thedump.idea_capture.core._cleanup_temp_file"
             -> "tests/unit/thedump/idea_capture/core/test__cleanup_temp_file.py"
    """
    parts = unit_name.split(".")
    if len(parts) < 2:
        # Fallback for simple names
        return f"tests/unit/test_{parts[0]}.py"

    # All parts except the last one form the directory path
    path_parts = parts[:-1]  # e.g., ["thedump", "idea_capture", "core"]
    unit = parts[-1]         # e.g., "_cleanup_temp_file"

    path = "/".join(path_parts)  # e.g., "thedump/idea_capture/core"
    return f"tests/unit/{path}/test_{unit}.py"


async def run_ratchet_red(
    unit: "UnitWorkItem",
    test_case: "TestCase",
    production_dir: Path,
    get_test_inventory: Callable[[Path], Set[str]],
    max_retries: int = MAX_RATCHET_RED_RETRIES,
) -> RatchetRedResult:
    """
    Run the Tester agent to write exactly one failing test.

    Args:
        unit: The unit being tested
        test_case: The specific test case to implement
        production_dir: Path to production/ directory
        get_test_inventory: Function to get set of test IDs from tests dir
        max_retries: Maximum retry attempts

    Returns:
        RatchetRedResult with success status and test file path
    """
    production_dir = Path(production_dir)
    tests_dir = production_dir / "tests"
    tests_dir.mkdir(exist_ok=True)

    # Calculate exact test file path and function name
    test_file_path = _calculate_test_file_path(unit.name)
    test_function_name = test_case.test_function_name

    # Create permission handler with tests_dir and unit_file_path bound
    # unit.module_path is relative to production_dir, so we need to make it absolute
    unit_file_path = production_dir / unit.module_path

    async def pre_tool_use_hook(
        hook_input: dict,
        tool_use_id: str | None,
        context: HookContext,
    ) -> dict:
        """PreToolUse hook to enforce permissions for Red agent."""
        tool_name = hook_input.get("tool_name", "")
        tool_input = hook_input.get("tool_input", {})
        print(f"[HOOK-RED] PreToolUse: tool={tool_name}, input={tool_input}")

        result = permission_handler(tool_name, tool_input, tests_dir, unit_file_path)

        if isinstance(result, PermissionResultDeny):
            print(f"[HOOK-RED] BLOCKING: {result.message}")
            return {
                "continue_": False,
                "decision": "block",
                "reason": result.message,
            }

        print(f"[HOOK-RED] ALLOWING")
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
        max_turns=15,
    )

    # Set env var for file checkpointing
    os.environ["CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING"] = "1"

    # Extract only the signature to avoid leaking prototype implementation
    unit_signature = _extract_signature(unit.code)

    base_prompt = f"""Write exactly ONE failing test for this unit.

## Unit Information
Name: {unit.name}
Module: {unit.module_path}

## Unit Description (from Oracle)
{unit.description}

## Function/Class Signature
```python
{unit_signature}
```

## Test Case Specification
{test_case.description}

## REQUIRED Test Location
You MUST create the test in this EXACT file path: {test_file_path}
You MUST name the test function EXACTLY: {test_function_name}

## Instructions
1. Create the directory structure if it doesn't exist (tests/unit/...)
2. Create or edit the test file at the EXACT path specified above
3. Write exactly ONE test function with the EXACT name specified above
4. The test should import and call the function/class being tested

CRITICAL: Use the exact file path and function name specified above.

CRITICAL: DO NOT RUN THE TESTS. I, THE USER, WILL RUN THEM FOR YOU AND PASTE THE OUTPUT.
"""

    retries = 0
    prompt = base_prompt

    try:
        # Context manager OUTSIDE retry loop to preserve conversation context
        async with ClaudeSDKClient(options=options) as client:
            while retries < max_retries:
                checkpoint_id = None

                # Get test inventory BEFORE agent runs
                tests_before = get_test_inventory(tests_dir)
                logger.info(f"[RATCHET-RED] Tests before: {len(tests_before)}")

                try:
                    logger.info(f"[RATCHET-RED] Sending prompt to tester agent (attempt {retries + 1}/{max_retries})")
                    await client.query(prompt)

                    # Capture checkpoint from first user message and process responses
                    async for message in client.receive_response():
                        _log_message(message)
                        if isinstance(message, UserMessage) and hasattr(message, 'uuid') and message.uuid and not checkpoint_id:
                            checkpoint_id = message.uuid
                            logger.info(f"[RATCHET-RED] Captured checkpoint: {checkpoint_id}")
                        if isinstance(message, ResultMessage):
                            if message.is_error:
                                raise Exception(message.result or "Agent error")

                    # Verify the test file was actually created
                    expected_file = production_dir / test_file_path
                    if not expected_file.exists():
                        error_msg = f"Test file was not created at expected path: {expected_file}"
                        logger.error(f"[RATCHET-RED] {error_msg}")

                        if checkpoint_id:
                            logger.info(f"[RATCHET-RED] Rewinding to checkpoint {checkpoint_id}")
                            await client.rewind_files(checkpoint_id)

                        retries += 1
                        if retries < max_retries:
                            prompt = f"{base_prompt}\n\nPREVIOUS ATTEMPT FAILED: {error_msg}\nMake sure to create the file at the EXACT path specified."
                            continue

                        return RatchetRedResult(
                            success=False,
                            error=error_msg,
                            retries=retries,
                        )

                    logger.info(f"[RATCHET-RED] Verified file exists: {expected_file}")

                    # Get test inventory AFTER agent runs
                    tests_after = get_test_inventory(tests_dir)
                    new_tests = tests_after - tests_before
                    logger.info(f"[RATCHET-RED] Tests after: {len(tests_after)}, new tests: {len(new_tests)}")

                    # Validate exactly 1 new test was added
                    if len(new_tests) != 1:
                        error_msg = f"Expected exactly 1 new test, got {len(new_tests)}"
                        if new_tests:
                            error_msg += f": {new_tests}"
                        logger.warning(f"[RATCHET-RED] Validation failed: {error_msg}")

                        # Rewind and retry
                        if checkpoint_id:
                            logger.info(f"[RATCHET-RED] Rewinding to checkpoint {checkpoint_id}")
                            await client.rewind_files(checkpoint_id)

                        retries += 1
                        if retries < max_retries:
                            prompt = f"{base_prompt}\n\nPREVIOUS ATTEMPT FAILED: {error_msg}\nPlease write exactly ONE test function. Not zero, not two - exactly one."
                            continue

                        return RatchetRedResult(
                            success=False,
                            error=error_msg,
                            retries=retries,
                        )

                    # We have exactly 1 new test - run final validation
                    new_test_id = new_tests.pop()
                    logger.info(f"[RATCHET-RED] New test: {new_test_id}")

                    # Final validation: verify test adheres to specification
                    logger.info("[RATCHET-RED] Running Pydantic AI validation...")
                    validation = await validate_test(
                        unit_name=unit.name,
                        unit_code=unit_signature,  # Use signature only, not prototype code
                        test_spec=test_case.description,
                        test_file_path=new_test_id,
                        tests_dir=tests_dir,
                    )

                    if not validation.is_valid:
                        logger.warning(f"[RATCHET-RED] Validation rejected: {validation.reason}")

                        # Rewind and retry with feedback
                        if checkpoint_id:
                            logger.info(f"[RATCHET-RED] Rewinding to checkpoint {checkpoint_id}")
                            await client.rewind_files(checkpoint_id)

                        retries += 1
                        if retries < max_retries:
                            prompt = f"{base_prompt}\n\nPREVIOUS TEST REJECTED: {validation.reason}\nPlease fix the test to correctly implement the specification."
                            continue

                        return RatchetRedResult(
                            success=False,
                            error=f"Test validation failed: {validation.reason}",
                            retries=retries,
                        )

                    # Validation passed - now run pytest to verify test fails
                    logger.info("[RATCHET-RED] Running pytest to verify test fails...")
                    pytest_result = run_pytest(production_dir, new_test_id)

                    if pytest_result.success:
                        # Test passed! This is wrong - it should fail
                        logger.warning("[RATCHET-RED] Test passed but should fail!")

                        # After 2 tries, invoke the arbiter to decide keep/discard
                        if retries >= 1:
                            logger.info("[RATCHET-RED] Test passed twice. Invoking Test Arbiter...")

                            decision = await arbitrate_test(
                                test_spec=test_case.description,
                                test_file_path=new_test_id,
                                test_function_name=test_function_name,
                                tests_dir=tests_dir,
                            )

                            if decision.keep_test:
                                logger.info(
                                    f"[RATCHET-RED] Arbiter: KEEP test "
                                    f"(confidence={decision.confidence_value}, "
                                    f"communication={decision.communication_value})"
                                )
                                logger.info(f"[RATCHET-RED] Reasoning: {decision.reasoning}")
                                return RatchetRedResult(
                                    success=True,
                                    test_file_path=new_test_id,
                                    retries=retries,
                                    skipped_green=True,  # Skip Green phase
                                )
                            else:
                                logger.info(f"[RATCHET-RED] Arbiter: DISCARD test - {decision.reasoning}")
                                if checkpoint_id:
                                    logger.info(f"[RATCHET-RED] Rewinding to checkpoint {checkpoint_id}")
                                    await client.rewind_files(checkpoint_id)
                                return RatchetRedResult(
                                    success=True,  # Not a failure, just skipped
                                    test_file_path="",
                                    retries=retries,
                                    skipped_green=True,  # Skip Green phase
                                )

                        # First try - rewind and retry
                        if checkpoint_id:
                            logger.info(f"[RATCHET-RED] Rewinding to checkpoint {checkpoint_id}")
                            await client.rewind_files(checkpoint_id)

                        retries += 1
                        if retries < max_retries:
                            prompt = f"{base_prompt}\n\nPREVIOUS ATTEMPT FAILED: The test passed but it should FAIL. Ensure the test correctly verifies the expected behavior from the specification."
                            continue

                        return RatchetRedResult(
                            success=False,
                            error="Test passed but should fail",
                            retries=retries,
                        )

                    # Test failed as expected - success!
                    logger.info(f"[RATCHET-RED] Test fails as expected: {new_test_id}")
                    return RatchetRedResult(
                        success=True,
                        test_file_path=new_test_id,
                        retries=retries,
                        pytest_failure=pytest_result.output,
                    )

                except Exception as e:
                    logger.error(f"[RATCHET-RED] Error: {e}")
                    retries += 1
                    if retries >= max_retries:
                        return RatchetRedResult(
                            success=False,
                            error=str(e),
                            retries=retries,
                        )
                    prompt = f"{base_prompt}\n\nPREVIOUS ATTEMPT ERROR: {e}\nPlease try again."

            return RatchetRedResult(
                success=False,
                error="Max retries exceeded",
                retries=retries,
            )

    except Exception as e:
        logger.error(f"[RATCHET-RED] Fatal error: {e}")
        return RatchetRedResult(
            success=False,
            error=str(e),
            retries=retries,
        )
