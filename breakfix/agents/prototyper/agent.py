import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Callable, Awaitable

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    ResultMessage,
    AssistantMessage,
    UserMessage,
    TextBlock,
)
from breakfix.agents.analyst import TestFixture

MAX_PROTOTYPER_ITERATIONS = 5
logger = logging.getLogger(__name__)


@dataclass
class PrototyperResult:
    success: bool
    iterations: int
    error: str = ""


async def run_prototyper(
    working_dir: str,
    spec: str,
    fixtures: List[TestFixture],
    package_name: str,
    run_e2e_test: Callable,  # Injected test runner
    interface_description: str = "",  # Description of expected I/O interface
) -> PrototyperResult:
    """
    Implement a prototype using ClaudeSDKClient with feedback loop.
    """
    proto_dir = Path(working_dir) / "prototype"

    # Build initial prompt (no mention of tests)
    prompt = _build_initial_prompt(spec, fixtures, package_name, interface_description)

    options = ClaudeAgentOptions(
        cwd=str(proto_dir),
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch"],
        permission_mode="acceptEdits",
        max_turns=30,
    )

    async with ClaudeSDKClient(options=options) as client:
        # Initial implementation request
        logger.info("[PROTOTYPER] Sending initial prompt to Claude:")
        logger.info("=" * 60)
        logger.info(prompt)
        logger.info("=" * 60)

        await client.query(prompt)

        # Wait for completion
        async for message in client.receive_response():
            _log_message(message)
            if isinstance(message, ResultMessage):
                if message.is_error:
                    return PrototyperResult(
                        success=False,
                        iterations=1,
                        error=message.result or "Unknown error"
                    )

        # Feedback loop
        for iteration in range(1, MAX_PROTOTYPER_ITERATIONS + 1):
            logger.info(f"[PROTOTYPER] Iteration {iteration}/{MAX_PROTOTYPER_ITERATIONS}: Running E2E tests...")

            # Run E2E tests
            test_result = await run_e2e_test(proto_dir, package_name)

            if test_result.success:
                logger.info(f"[PROTOTYPER] E2E tests passed on iteration {iteration}")
                return PrototyperResult(success=True, iterations=iteration)

            logger.info(f"[PROTOTYPER] E2E tests failed. Error:\n{test_result.error}")

            if iteration == MAX_PROTOTYPER_ITERATIONS:
                return PrototyperResult(
                    success=False,
                    iterations=iteration,
                    error=f"Max iterations reached. Last error:\n{test_result.error}"
                )

            # Send test failure to Claude for fixing
            fix_prompt = _build_fix_prompt(test_result.error)
            logger.info("[PROTOTYPER] Sending fix prompt to Claude:")
            logger.info("=" * 60)
            logger.info(fix_prompt)
            logger.info("=" * 60)

            await client.query(fix_prompt)

            async for message in client.receive_response():
                _log_message(message)
                if isinstance(message, ResultMessage):
                    if message.is_error:
                        return PrototyperResult(
                            success=False,
                            iterations=iteration,
                            error=message.result or "Fix attempt failed"
                        )

    return PrototyperResult(success=False, iterations=0, error="Unexpected exit")


def _log_message(message):
    """Log messages from Claude SDK."""
    if isinstance(message, AssistantMessage):
        logger.info("[CLAUDE] Assistant message:")
        for block in message.content:
            if isinstance(block, TextBlock):
                logger.info(f"  Text: {block.text}")
            else:
                logger.info(f"  {type(block).__name__}: {block}")
    elif isinstance(message, UserMessage):
        logger.info(f"[CLAUDE] User message: {message.content}")
    elif isinstance(message, ResultMessage):
        logger.info(f"[CLAUDE] Result: is_error={message.is_error}, result={message.result}")
    else:
        logger.info(f"[CLAUDE] {type(message).__name__}: {message}")


def _build_initial_prompt(spec: str, fixtures: List[TestFixture], package_name: str, interface_description: str = "") -> str:
    """Build the initial prompt for Claude (no mention of tests)."""
    fixture_examples = "\n".join([
        f"- Input: {f.input_data} → Expected: {f.expected_output}"
        for f in fixtures[:3]  # Show first 3 as examples
    ])

    interface_section = ""
    if interface_description:
        interface_section = f"""
## Program Interface (CRITICAL - must match exactly)
{interface_description}
"""

    return f"""Implement a Python program based on the following specification.

## Specification
{spec}

## Expected Behaviors
The program should handle these input/output cases:
{fixture_examples}
{interface_section}
## Requirements
1. Read the existing project structure first to understand the layout
2. The project uses PyScaffold - modify `src/{package_name}/skeleton.py`
3. The `skeleton.py` file has a `run()` function that is the CLI entrypoint
4. The CLI will be invoked as `{package_name}` command (already configured)
5. Do NOT create any test files - only implementation code
6. The program interface should match what the specification describes

## Installing Dependencies
If you need external packages, install them using the project's virtualenv:
```bash
.venv/bin/pip install <package_name>
```
Also add them to the `install_requires` list in `setup.cfg` under the `[options]` section.

Start by reading the existing skeleton.py file, then implement the solution by modifying it.
"""


def _build_fix_prompt(error_output: str) -> str:
    """Build a prompt asking Claude to fix issues."""
    return f"""The program has issues. Here's the output from running it:

```
{error_output}
```

Please fix the implementation to resolve these issues. Remember:
- Only modify implementation files (skeleton.py), do NOT create tests
- The CLI entrypoint is the `run()` function in skeleton.py
"""
