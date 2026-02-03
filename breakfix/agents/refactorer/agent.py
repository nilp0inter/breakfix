import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Awaitable

from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage, AssistantMessage, TextBlock, ToolUseBlock

from breakfix.agents.architecture_reviewer import ReviewerOutput
from breakfix.artifacts import agent_input_artifact, agent_output_artifact, agent_iteration_artifact

MAX_REFACTOR_ITERATIONS = 5


@dataclass
class RefactorerResult:
    success: bool
    iterations: int
    error: str = ""


async def run_refactorer(
    working_dir: str,
    package_name: str,
    run_e2e_test: Callable,
    review_architecture: Callable[[Path], Awaitable[ReviewerOutput]],
) -> RefactorerResult:
    """
    Refactor prototype into FCIS architecture.

    Flow:
    1. Run ArchitectureReviewer to check for violations
    2. If clean → return success
    3. If violations → Claude fixes → run E2E tests → if E2E fails → Claude fixes E2E → goto 1
    """
    start_time = time.time()
    proto_dir = Path(working_dir) / "prototype"
    src_dir = proto_dir / "src" / package_name

    print("[REFACTORER] ========================================")
    print(f"[REFACTORER] Starting FCIS refactoring")
    print(f"[REFACTORER] Working directory: {working_dir}")
    print(f"[REFACTORER] Package: {package_name}")
    print(f"[REFACTORER] Max iterations: {MAX_REFACTOR_ITERATIONS}")
    print("[REFACTORER] ========================================")

    # Create input artifact
    await agent_input_artifact(
        agent_name="refactorer",
        prompt=f"Refactor {package_name} to FCIS architecture",
        context={
            "working_dir": working_dir,
            "package_name": package_name,
            "max_iterations": MAX_REFACTOR_ITERATIONS,
        },
    )

    options = ClaudeAgentOptions(
        cwd=str(proto_dir),
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        permission_mode="acceptEdits",
        max_turns=50,
    )

    for iteration in range(1, MAX_REFACTOR_ITERATIONS + 1):
        print(f"[REFACTORER] ----------------------------------------")
        print(f"[REFACTORER] Iteration {iteration}/{MAX_REFACTOR_ITERATIONS}")
        print(f"[REFACTORER] ----------------------------------------")

        await agent_iteration_artifact(
            agent_name="refactorer",
            iteration=iteration,
            max_iterations=MAX_REFACTOR_ITERATIONS,
            status="running",
            details="Running architecture review",
        )

        # Step 1: Review architecture
        print("[REFACTORER] Running ArchitectureReviewer...")
        review_result = await review_architecture(src_dir)

        # Step 2: If clean, we're done!
        if review_result.is_clean:
            duration = time.time() - start_time
            print(f"[REFACTORER] SUCCESS: Architecture is clean on iteration {iteration}")
            print(f"[REFACTORER] Total duration: {duration:.1f}s")
            await agent_iteration_artifact(
                agent_name="refactorer",
                iteration=iteration,
                max_iterations=MAX_REFACTOR_ITERATIONS,
                status="completed",
                details="Architecture is clean - FCIS compliant",
            )
            await agent_output_artifact(
                agent_name="refactorer",
                result=f"Successfully refactored to FCIS architecture in {iteration} iteration(s)",
                success=True,
                duration_seconds=duration,
            )
            return RefactorerResult(success=True, iterations=iteration)

        # Check if max iterations reached
        if iteration == MAX_REFACTOR_ITERATIONS:
            duration = time.time() - start_time
            error_msg = f"Max iterations reached. Remaining violations: {review_result.summary}"
            print(f"[REFACTORER] FAILED: {error_msg}")
            await agent_iteration_artifact(
                agent_name="refactorer",
                iteration=iteration,
                max_iterations=MAX_REFACTOR_ITERATIONS,
                status="failed",
                details=error_msg,
            )
            await agent_output_artifact(
                agent_name="refactorer",
                result=error_msg,
                success=False,
                duration_seconds=duration,
            )
            return RefactorerResult(
                success=False,
                iterations=iteration,
                error=f"Violations: {review_result.summary}"
            )

        # Step 3: Violations found - call Claude to fix
        print(f"[REFACTORER] Found {len(review_result.violations)} violations:")
        print(f"[REFACTORER] Summary: {review_result.summary}")
        for v in review_result.violations:
            print(f"[REFACTORER]   - {v.file_path}::{v.function_or_class} [{v.violation_type}]")
            print(f"[REFACTORER]     {v.description}")
            if v.code_snippet:
                snippet_lines = v.code_snippet.split('\n')[:3]
                for line in snippet_lines:
                    print(f"[REFACTORER]       {line[:80]}")

        await agent_iteration_artifact(
            agent_name="refactorer",
            iteration=iteration,
            max_iterations=MAX_REFACTOR_ITERATIONS,
            status="running",
            details=f"Fixing {len(review_result.violations)} violations",
        )

        refactor_prompt = _build_refactor_prompt(review_result, package_name)
        print("[REFACTORER] Sending refactor prompt to Claude...")
        async for message in query(prompt=refactor_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        lines = block.text.split('\n')[:3]
                        for line in lines:
                            print(f"[REFACTORER]   {line[:80]}")
                    elif isinstance(block, ToolUseBlock):
                        print(f"[REFACTORER]   Tool: {block.name}")
            if isinstance(message, ResultMessage) and message.is_error:
                duration = time.time() - start_time
                error_msg = f"Refactor failed on iteration {iteration}"
                print(f"[REFACTORER] ERROR: {error_msg}")
                await agent_output_artifact(
                    agent_name="refactorer",
                    result=error_msg,
                    success=False,
                    duration_seconds=duration,
                )
                return RefactorerResult(success=False, iterations=iteration, error="Refactor failed")

        # Step 4: Run E2E tests after refactoring to verify we didn't break anything
        print("[REFACTORER] Running E2E tests after refactor...")
        test_result = await run_e2e_test(proto_dir, package_name)

        # Step 5: If E2E failed, call Claude to fix
        if not test_result.success:
            print(f"[REFACTORER] E2E tests failed: {test_result.error}")
            await agent_iteration_artifact(
                agent_name="refactorer",
                iteration=iteration,
                max_iterations=MAX_REFACTOR_ITERATIONS,
                status="running",
                details=f"E2E tests failed, attempting fix: {test_result.error[:100]}",
            )
            fix_prompt = _build_e2e_fix_prompt(test_result.error, package_name)
            print("[REFACTORER] Sending E2E fix prompt to Claude...")
            async for message in query(prompt=fix_prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            lines = block.text.split('\n')[:3]
                            for line in lines:
                                print(f"[REFACTORER]   {line[:80]}")
                        elif isinstance(block, ToolUseBlock):
                            print(f"[REFACTORER]   Tool: {block.name}")
                if isinstance(message, ResultMessage) and message.is_error:
                    duration = time.time() - start_time
                    error_msg = f"E2E fix failed on iteration {iteration}"
                    print(f"[REFACTORER] ERROR: {error_msg}")
                    await agent_output_artifact(
                        agent_name="refactorer",
                        result=error_msg,
                        success=False,
                        duration_seconds=duration,
                    )
                    return RefactorerResult(success=False, iterations=iteration, error="E2E fix failed")
        else:
            print("[REFACTORER] E2E tests passed after refactor")

    duration = time.time() - start_time
    error_msg = "Unexpected exit from refactorer loop"
    print(f"[REFACTORER] ERROR: {error_msg}")
    await agent_output_artifact(
        agent_name="refactorer",
        result=error_msg,
        success=False,
        duration_seconds=duration,
    )
    return RefactorerResult(success=False, iterations=MAX_REFACTOR_ITERATIONS, error="Unexpected exit")


def _build_refactor_prompt(result: ReviewerOutput, package_name: str) -> str:
    violations_text = "\n".join([
        f"- {v.file_path}::{v.function_or_class} [{v.violation_type}]: {v.description}\n  Code: {v.code_snippet}\n  Suggestion: {v.suggestion}"
        for v in result.violations
    ])
    return f"""Refactor this code to follow the Functional Core/Imperative Shell (FCIS) pattern.

## Current Violations
{violations_text}

Summary: {result.summary}

## Target Structure
Organize into domain-based subpackages:

```
src/{package_name}/
    __init__.py
    parser.py                # Argument parsing (argparse/click)
    cli.py                   # main() function - the entrypoint
    <domain_name>/           # e.g., payments/, users/, orders/
        __init__.py          # Wires dependencies, exports ready-to-use functions
        model.py             # Domain-specific dataclasses
        core.py              # Pure functions with dependency injection
        shell.py             # I/O adapters that convert errors to data
```

Choose meaningful domain names based on the business logic.

## FCIS Philosophy

### model.py - Domain-Specific Data Structures
Use meaningful domain names, NOT generic Success/Failure:

```python
from dataclasses import dataclass

# Domain-specific result types
@dataclass
class PaymentApproved:
    transaction_id: str
    amount: float

@dataclass
class PaymentDenied:
    reason: str

@dataclass
class InsufficientFunds:
    available: float
    required: float

# Domain-specific input/output types
@dataclass
class PaymentRequest:
    account_id: str
    amount: float
```

### core.py - Dependency Injection Pattern
Use higher-order functions to inject **shell functions** (I/O adapters):

```python
from typing import Callable
from .model import PaymentApproved, PaymentDenied, InsufficientFunds, BankResponse

def create_process_payment(
    fetch_from_bank: Callable,  # Shell function - must be injected
    save_transaction: Callable,  # Shell function - must be injected
):
    \"\"\"Factory that returns the use case with shell dependencies baked in.\"\"\"
    def process_payment(request) -> PaymentApproved | PaymentDenied | InsufficientFunds:
        # Pure logic here - shell functions are callables passed in
        bank_result = fetch_from_bank(request.account_id, request.amount)
        match bank_result:
            case BankDenied(reason):
                return PaymentDenied(reason=reason)
            case BankApproved(tx_id):
                save_transaction(tx_id, request.amount)
                return PaymentApproved(transaction_id=tx_id, amount=request.amount)
    return process_payment
```

**What to inject**: Only shell functions (I/O adapters)
**What NOT to inject**: Pure business logic - can be imported and called directly

### shell.py - I/O Adapters
```python
from .model import BankResponse, BankUnavailable, PaymentRequest, InvalidInput

def fetch_from_bank(account_id: str, amount: float) -> BankResponse | BankUnavailable:
    \"\"\"Only catch exceptions the core can meaningfully handle.\"\"\"
    try:
        response = requests.post(BANK_API, json={...})
        if response.ok:
            return BankResponse(approved=True, tx_id=response.json()["id"])
        return BankResponse(approved=False, reason=response.json()["error"])
    except (requests.Timeout, requests.ConnectionError) as e:
        # Core can retry or show "bank unavailable" - this is domain-relevant
        return BankUnavailable(reason=str(e))
    # Let MemoryError, KeyboardInterrupt, etc. bubble up - core can't handle them

def read_payment_request() -> PaymentRequest | InvalidInput:
    try:
        data = json.loads(input())
        return PaymentRequest(**data)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        # Core can handle bad input - domain-relevant
        return InvalidInput(reason=str(e))
    # Don't catch EOFError separately if InvalidInput covers "no valid input"
```

**Key principle**: Only capture exceptions the core logic can do something meaningful about.
If core can't handle it (MemoryError, SystemExit), let it bubble up.

### Subpackage __init__.py - Lazy Dependency Wiring
Each subpackage's `__init__.py` defines builder functions for lazy wiring:
```python
# payments/__init__.py
from .core import create_process_payment
from .shell import fetch_from_bank, save_transaction
from .model import PaymentApproved, PaymentDenied, InsufficientFunds

# Lazy loading - returns wired function when called (not at import time)
build_process_payment = lambda: create_process_payment(fetch_from_bank, save_transaction)

# Export builders and models
__all__ = ["build_process_payment", "create_process_payment", "PaymentApproved", "PaymentDenied", "InsufficientFunds"]
```

This allows:
- Users get wired functions: `process_payment = build_process_payment()`
- Import succeeds even if shell functions are stubbed
- Tests can create custom instances: `create_process_payment(mock_fetch, mock_save)`

### parser.py - Argument Parsing
```python
import argparse

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process payments")
    parser.add_argument("--amount", type=float, required=True)
    return parser
```

### cli.py - Main Entrypoint
```python
import sys
from .parser import create_parser
from .payments import build_process_payment, PaymentApproved, PaymentDenied, InsufficientFunds

def main():
    parser = create_parser()
    args = parser.parse_args()
    process_payment = build_process_payment()
    result = process_payment(args.amount)
    match result:
        case PaymentApproved(transaction_id=tx):
            print(f"Approved: {{tx}}")
        case PaymentDenied(reason=r):
            print(f"Denied: {{r}}", file=sys.stderr)
            sys.exit(1)
        case InsufficientFunds(available=a, required=r):
            print(f"Insufficient: {{a}} < {{r}}", file=sys.stderr)
            sys.exit(1)
```

### Rules for core.py
- NO imports: os, sys, random, io, socket, subprocess, pathlib, requests
- NO calls: print(), input(), open(), exec(), eval()
- NO raised exceptions for business logic
- ALL dependencies received as function parameters
- ALL outcomes returned as domain-specific dataclasses from model.py

### Rules for shell.py
- Only capture exceptions the core can meaningfully handle
- Let irrelevant exceptions bubble up (MemoryError, KeyboardInterrupt, etc.)
- Convert domain-relevant errors to dataclasses (NOT 1:1 exception mapping)
- Thin adapters - no business logic
- Can use os, sys, requests, etc.

### Rules for model.py
- Only dataclass definitions
- No logic, no I/O
- Use domain-specific names (NOT generic Success/Failure)
- NO 1:1 mappings of Python exceptions - use domain abstractions
  (e.g., ConfigNotReadable(reason="...") instead of FileNotFoundError/PermissionError/etc.)

Read the current code and refactor to fix all violations."""


def _build_e2e_fix_prompt(error: str, package_name: str) -> str:
    return f"""The E2E tests failed after refactoring:

```
{error}
```

The FCIS architecture should be maintained:
- src/{package_name}/<domain>/model.py - Domain-specific dataclasses (e.g., PaymentApproved, UserNotFound)
- src/{package_name}/<domain>/core.py - Pure functions with dependency injection
- src/{package_name}/<domain>/shell.py - I/O adapters returning domain-specific types
- src/{package_name}/<domain>/__init__.py - Lazy wiring with build_* lambdas
- src/{package_name}/parser.py - Argument parsing
- src/{package_name}/cli.py - main() entrypoint, handles outcomes with match/case

Fix the implementation while keeping this structure. The CLI interface must work correctly."""
