import json
from pathlib import Path
from typing import List
from dataclasses import dataclass

from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

from breakfix.agents.analyst import TestFixture


@dataclass
class E2EBuilderResult:
    """Result from E2E test builder."""
    success: bool
    error: str = ""


async def run_e2e_builder(
    working_dir: str,
    fixtures: List[TestFixture],
    spec: str
) -> E2EBuilderResult:
    """
    Create E2E test harness using Claude Agent SDK.

    1. Creates e2e-tests/ directory
    2. Writes fixtures.json
    3. Uses Claude Code to generate run_tests.py
    """
    e2e_dir = Path(working_dir) / "e2e-tests"
    e2e_dir.mkdir(parents=True, exist_ok=True)

    # Write fixtures to JSON
    fixtures_data = [f.model_dump() for f in fixtures]
    fixtures_path = e2e_dir / "fixtures.json"
    fixtures_path.write_text(json.dumps(fixtures_data, indent=2))

    # Build prompt for Claude Code
    fixture_example = json.dumps(fixtures_data[0] if fixtures_data else {}, indent=2)

    prompt = f"""You need to create TWO things in the current directory:

## CRITICAL: Black-Box Testing Principle

This is BLACK-BOX testing. The test harness and the program under test MUST be completely decoupled:
- run_tests.py CANNOT import, load, or inspect mock_program.py in any way
- run_tests.py can ONLY interact with the program by:
  - Spawning it as a subprocess
  - Sending input (stdin, CLI args, HTTP requests, etc.)
  - Reading output (stdout, HTTP responses, etc.)
- The program is a black box - treat it as an opaque executable

## CRITICAL: Subprocess Execution Rules

When spawning the program under test, run_tests.py MUST follow these rules:

1. **NEVER use sys.executable to force the Python interpreter**
   BAD:  subprocess.Popen([sys.executable, program_path], ...)
   GOOD: subprocess.Popen([program_path], ...)

   Why: Using sys.executable ignores the program's shebang and can cause environment
   mismatches. If the program is an installed entry point (e.g., from `pip install`),
   forcing a different Python interpreter will cause ModuleNotFoundError because the
   package won't be importable in that environment.

2. **NEVER suppress stderr**
   BAD:  stderr=subprocess.DEVNULL
   GOOD: stderr=subprocess.PIPE (and capture/display it on failure)

   Why: Suppressing stderr hides critical errors like ModuleNotFoundError, making
   failures appear as mysterious timeouts instead of clear import errors.

3. **Execute programs directly, respecting their shebang**
   The program path should be executed directly: [program_path] or [program_path, args...]
   This allows:
   - Standalone scripts to use their #!/usr/bin/env python3 shebang
   - Installed entry points to use their virtualenv's Python
   - Any executable to run in its intended environment

4. **Always capture and report stderr on failure**
   When a process fails to start or times out, print stderr to help diagnose issues.
   Example:
   ```python
   process = subprocess.Popen([program_path], stderr=subprocess.PIPE, ...)
   # ... on failure:
   stderr_output = process.stderr.read().decode() if process.stderr else ""
   print(f"Process failed. stderr: {{stderr_output}}")
   ```

## Task 1: Create run_tests.py (E2E test harness)

Create a Python test script called run_tests.py that:
1. Reads fixtures.json which contains test cases with fields: name, description, input_data, expected_output
2. Accepts a program path as the first command line argument
3. For each fixture:
   - Spawns the program as a subprocess (do NOT import it)
   - Sends input_data via the appropriate interface (determine from spec below)
   - The interface could be: stdin/stdout, CLI arguments, HTTP request/response, etc.
   - Reads the program's output
   - Compares the actual result with expected_output
   - Prints pass/fail status with details for each test
4. Prints a summary at the end
5. Exits with code 0 if all tests pass, exits with code 1 if any test fails

IMPORTANT: run_tests.py must work with ANY program that implements the correct interface, not just mock_program.py.

## Task 2: Create mock_program.py (Stub for fixture verification)

Create a MINIMAL stub program called mock_program.py that:
1. Is NOT a general-purpose implementation - it's just a stub for testing the harness
2. Hardcodes responses based on the fixture data (can read fixtures.json or hardcode values)
3. For each known input from fixtures, returns the corresponding expected_output
4. Uses the same interface the real program would use (stdin/stdout, CLI args, HTTP, etc.)
5. Does NOT need to handle any inputs outside the fixtures - it's a stub, not a real program
6. MUST be executable - add a shebang line (#!/usr/bin/env python3) and make it executable with chmod +x

The mock_program.py exists ONLY to verify that run_tests.py works correctly. It should be the simplest possible implementation that makes all fixture tests pass.

## CRITICAL: Zero-Configuration Requirement for mock_program.py

mock_program.py MUST be completely self-contained and run with ZERO prerequisites:
- NO command-line arguments required
- NO environment variables required
- NO configuration files required
- NO external services or open ports required before launch
- NO setup or initialization by run_tests.py

When executed as `./mock_program.py` it MUST work on the FIRST TRY with no preparation.

If the program is an HTTP server, it must:
- Start itself and bind to a HARDCODED port (e.g., 8080)
- The port number must be HARDCODED in BOTH mock_program.py AND run_tests.py
- run_tests.py must spawn mock_program.py, wait for it to be ready, then send requests

If the program reads stdin, it must:
- Read from stdin with no arguments needed
- run_tests.py spawns it and pipes input via stdin

The communication interface (ports, protocols, formats) must be HARDCODED in both files - run_tests.py must NOT pass configuration to mock_program.py.

IMPORTANT: After creating mock_program.py, run: chmod +x mock_program.py

This is critical because the verification step will run:
  cd e2e-tests && python run_tests.py $(pwd)/mock_program.py

## Task 3: Verify everything works together

After creating both files:
1. Run: python run_tests.py ./mock_program.py (or appropriate invocation)
2. ALL tests must pass
3. If any test fails, fix the issue and try again
4. Only stop when all tests pass successfully

## Specification (use this to determine program interface):
{spec}

## Fixture structure (from fixtures.json):
{fixture_example}

Start by creating run_tests.py, then mock_program.py, then verify they work together.
"""

    options = ClaudeAgentOptions(
        cwd=str(e2e_dir),
        allowed_tools=["Read", "Write", "Edit", "Bash"],
        permission_mode="acceptEdits",
        max_turns=30,
    )

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                if message.is_error:
                    return E2EBuilderResult(
                        success=False,
                        error=message.result or "Unknown error"
                    )

        # Verify both files were created
        if not (e2e_dir / "run_tests.py").exists():
            return E2EBuilderResult(
                success=False,
                error="run_tests.py was not created"
            )
        if not (e2e_dir / "mock_program.py").exists():
            return E2EBuilderResult(
                success=False,
                error="mock_program.py was not created"
            )

        return E2EBuilderResult(success=True)

    except Exception as e:
        return E2EBuilderResult(success=False, error=str(e))
