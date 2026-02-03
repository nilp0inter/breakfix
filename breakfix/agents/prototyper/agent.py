import time
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
    ToolUseBlock,
    ToolResultBlock,
)
from breakfix.agents.analyst import TestFixture
from breakfix.artifacts import (
    agent_input_artifact,
    agent_output_artifact,
    agent_iteration_artifact,
)

MAX_PROTOTYPER_ITERATIONS = 5


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
    run_e2e_test: Callable[[Path], Awaitable],  # Injected test runner (takes proto_dir)
    interface_description: str = "",  # Description of expected I/O interface
) -> PrototyperResult:
    """
    Implement a prototype using ClaudeSDKClient with feedback loop.
    """
    proto_dir = Path(working_dir) / "prototype"
    start_time = time.time()

    # Build initial prompt (no mention of tests)
    prompt = _build_initial_prompt(spec, fixtures, package_name, interface_description)

    options = ClaudeAgentOptions(
        cwd=str(proto_dir),
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch"],
        permission_mode="acceptEdits",
        max_turns=30,
    )

    print("[PROTOTYPER] ========================================")
    print("[PROTOTYPER] Starting prototype implementation")
    print(f"[PROTOTYPER] Working directory: {proto_dir}")
    print(f"[PROTOTYPER] Package name: {package_name}")
    print("[PROTOTYPER] ========================================")

    # Create input artifact
    await agent_input_artifact(
        agent_name="prototyper",
        prompt=prompt,
        context={
            "package_name": package_name,
            "num_fixtures": len(fixtures),
            "has_interface_desc": bool(interface_description),
        },
    )

    async with ClaudeSDKClient(options=options) as client:
        # Initial implementation request
        print("[PROTOTYPER] Sending initial prompt to Claude...")
        print("[PROTOTYPER] " + "=" * 50)
        for line in prompt.split("\n")[:20]:
            print(f"[PROTOTYPER] {line}")
        if len(prompt.split("\n")) > 20:
            print("[PROTOTYPER] ... (truncated)")
        print("[PROTOTYPER] " + "=" * 50)

        await client.query(prompt)

        # Wait for completion
        print("[PROTOTYPER] Waiting for Claude response...")
        async for message in client.receive_response():
            _log_message(message)
            if isinstance(message, ResultMessage):
                if message.is_error:
                    duration = time.time() - start_time
                    error_msg = message.result or "Unknown error"
                    await agent_output_artifact(
                        agent_name="prototyper",
                        result=error_msg,
                        success=False,
                        duration_seconds=duration,
                    )
                    return PrototyperResult(
                        success=False,
                        iterations=1,
                        error=error_msg
                    )

        print("[PROTOTYPER] Initial implementation complete")

        # Feedback loop
        for iteration in range(1, MAX_PROTOTYPER_ITERATIONS + 1):
            print(f"[PROTOTYPER] ----------------------------------------")
            print(f"[PROTOTYPER] Iteration {iteration}/{MAX_PROTOTYPER_ITERATIONS}: Running E2E tests...")

            # Create iteration artifact
            await agent_iteration_artifact(
                agent_name="prototyper",
                iteration=iteration,
                max_iterations=MAX_PROTOTYPER_ITERATIONS,
                status="running_tests",
                details="Running E2E tests to verify implementation",
            )

            # Run E2E tests (closure captures package_name)
            test_result = await run_e2e_test(proto_dir)

            if test_result.success:
                duration = time.time() - start_time
                print(f"[PROTOTYPER] E2E tests PASSED on iteration {iteration}")
                print(f"[PROTOTYPER] Total duration: {duration:.1f}s")

                await agent_output_artifact(
                    agent_name="prototyper",
                    result=f"Prototype completed successfully in {iteration} iteration(s)",
                    success=True,
                    duration_seconds=duration,
                )
                return PrototyperResult(success=True, iterations=iteration)

            print(f"[PROTOTYPER] E2E tests FAILED. Error:")
            for line in str(test_result.error).split("\n")[:15]:
                print(f"[PROTOTYPER]   {line}")
            if len(str(test_result.error).split("\n")) > 15:
                print("[PROTOTYPER]   ... (truncated)")

            # Update iteration artifact with failure
            await agent_iteration_artifact(
                agent_name="prototyper",
                iteration=iteration,
                max_iterations=MAX_PROTOTYPER_ITERATIONS,
                status="test_failed",
                details=str(test_result.error)[:1000],
            )

            if iteration == MAX_PROTOTYPER_ITERATIONS:
                duration = time.time() - start_time
                error_msg = f"Max iterations reached. Last error:\n{test_result.error}"
                await agent_output_artifact(
                    agent_name="prototyper",
                    result=error_msg,
                    success=False,
                    duration_seconds=duration,
                )
                return PrototyperResult(
                    success=False,
                    iterations=iteration,
                    error=error_msg
                )

            # Send test failure to Claude for fixing
            fix_prompt = _build_fix_prompt(test_result.error)
            print("[PROTOTYPER] Sending fix prompt to Claude...")
            print("[PROTOTYPER] " + "=" * 50)
            for line in fix_prompt.split("\n")[:10]:
                print(f"[PROTOTYPER] {line}")
            print("[PROTOTYPER] " + "=" * 50)

            await client.query(fix_prompt)

            print("[PROTOTYPER] Waiting for Claude fix response...")
            async for message in client.receive_response():
                _log_message(message)
                if isinstance(message, ResultMessage):
                    if message.is_error:
                        duration = time.time() - start_time
                        error_msg = message.result or "Fix attempt failed"
                        await agent_output_artifact(
                            agent_name="prototyper",
                            result=error_msg,
                            success=False,
                            duration_seconds=duration,
                        )
                        return PrototyperResult(
                            success=False,
                            iterations=iteration,
                            error=error_msg
                        )

    duration = time.time() - start_time
    await agent_output_artifact(
        agent_name="prototyper",
        result="Unexpected exit from agent loop",
        success=False,
        duration_seconds=duration,
    )
    return PrototyperResult(success=False, iterations=0, error="Unexpected exit")


def _log_message(message):
    """Log messages from Claude SDK with detailed output."""
    if isinstance(message, AssistantMessage):
        print("[PROTOTYPER] Claude response:")
        for block in message.content:
            if isinstance(block, TextBlock):
                # Print first few lines of text
                lines = block.text.split("\n")[:5]
                for line in lines:
                    print(f"[PROTOTYPER]   {line[:100]}")
                if len(block.text.split("\n")) > 5:
                    print("[PROTOTYPER]   ... (more text)")
            elif isinstance(block, ToolUseBlock):
                print(f"[PROTOTYPER]   Tool: {block.name}")
                # Show key parameters
                if hasattr(block, "input") and block.input:
                    if "file_path" in block.input:
                        print(f"[PROTOTYPER]     file: {block.input['file_path']}")
                    if "command" in block.input:
                        cmd = block.input["command"][:80]
                        print(f"[PROTOTYPER]     cmd: {cmd}...")
            else:
                print(f"[PROTOTYPER]   {type(block).__name__}")
    elif isinstance(message, UserMessage):
        content_str = str(message.content)[:100]
        print(f"[PROTOTYPER] User/Tool result: {content_str}...")
    elif isinstance(message, ResultMessage):
        status = "ERROR" if message.is_error else "COMPLETE"
        print(f"[PROTOTYPER] Agent {status}")
        if message.result:
            print(f"[PROTOTYPER]   Result: {str(message.result)[:100]}")
    else:
        print(f"[PROTOTYPER] {type(message).__name__}")


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
