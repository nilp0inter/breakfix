"""Test Arbiter - decides whether to keep or discard non-failing tests.

When a test passes immediately (when it should fail), the Arbiter evaluates
whether to keep or discard it based on Kent Beck's two criteria:
1. Confidence: Does the test increase confidence in the system?
2. Communication: Does the test document a meaningfully different scenario?
"""
import logging
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent


logger = logging.getLogger(__name__)


class ArbiterDecision(BaseModel):
    """Decision from the Test Arbiter."""
    keep_test: bool = Field(
        ...,
        description="True if test should be kept, False if discarded"
    )
    confidence_value: bool = Field(
        ...,
        description="Does this test increase confidence in the system?"
    )
    communication_value: bool = Field(
        ...,
        description="Does this test document a meaningfully different scenario?"
    )
    reasoning: str = Field(
        default="",
        description="Explanation of the decision"
    )


ARBITER_SYSTEM_PROMPT = """You are a TDD Test Arbiter. Your job is to decide whether to keep or discard
a test that passed immediately (when it should have failed).

According to Kent Beck's TDD principles, evaluate the test on TWO criteria:

## Criterion 1: CONFIDENCE
Does this test increase your confidence in the system's behavior?
- Does it protect against a failure mode that matters?
- Would removing it reduce safety?
- Even if redundant now, could future code changes make it valuable?

## Criterion 2: COMMUNICATION
Does this test document a meaningfully different scenario?
- Does it illustrate a different use case than existing tests?
- Does it help future developers understand the system's intent?
- Does it speak to a different aspect of the requirement?

## Decision Rules
- If BOTH criteria are FALSE → discard (keep_test=False)
- If EITHER criterion is TRUE → keep (keep_test=True)

Be pragmatic, not dogmatic. Tests are living documentation and safety nets.
"""


def create_arbiter(model: str = "openai:gpt-5") -> Agent[None, ArbiterDecision]:
    """Create Test Arbiter agent."""
    return Agent(
        model,
        output_type=ArbiterDecision,
        system_prompt=ARBITER_SYSTEM_PROMPT,
    )


def _mark_offending_test(test_file_content: str, test_function_name: str) -> str:
    """Insert a marker comment before the offending test function.

    Args:
        test_file_content: The complete test file content
        test_function_name: Name of the test function to mark

    Returns:
        Test file content with marker inserted before the offending test
    """
    lines = test_file_content.split('\n')
    result = []
    for line in lines:
        # Look for the test function definition
        stripped = line.strip()
        if (stripped.startswith(f'def {test_function_name}(') or
            stripped.startswith(f'def {test_function_name} (') or
            stripped.startswith(f'async def {test_function_name}(') or
            stripped.startswith(f'async def {test_function_name} (')):
            result.append("# >>> EVALUATING THIS TEST <<<")
        result.append(line)
    return '\n'.join(result)


async def arbitrate_test(
    test_spec: str,
    test_file_path: str,
    test_function_name: str,
    tests_dir: Path,
    model: str = "openai:gpt-5",
) -> ArbiterDecision:
    """Decide whether to keep or discard a non-failing test.

    Args:
        test_spec: The test case specification from Oracle
        test_file_path: Path to the test file (pytest node ID format)
        test_function_name: Name of the test function being evaluated
        tests_dir: Tests directory path
        model: LLM model to use

    Returns:
        ArbiterDecision with keep_test, confidence_value, communication_value, reasoning
    """
    # Extract file path from pytest node ID (e.g., "tests/test_core.py::test_func")
    if "::" in test_file_path:
        file_part, _ = test_file_path.split("::", 1)
    else:
        file_part = test_file_path

    # Read the complete test file
    test_file = tests_dir.parent / file_part
    if not test_file.exists():
        logger.error(f"[ARBITER] Test file not found: {test_file}")
        # Default to keep if we can't read the file
        return ArbiterDecision(
            keep_test=True,
            confidence_value=True,
            communication_value=False,
            reasoning=f"Could not read test file {test_file}, defaulting to keep"
        )

    test_file_content = test_file.read_text()
    logger.info(f"[ARBITER] Evaluating test '{test_function_name}' from {test_file}")

    # Mark the offending test in the file content
    marked_content = _mark_offending_test(test_file_content, test_function_name)

    agent = create_arbiter(model)

    prompt = f"""Evaluate whether to keep or discard a test that passed immediately.

## Test Specification (for the offending test)
{test_spec}

## Complete Test File
The file below contains ALL tests implemented so far for this unit.
The test being evaluated is marked with ">>> EVALUATING THIS TEST <<<".

```python
{marked_content}
```

## Offending Test Function Name
{test_function_name}

## Context
- The marked test PASSED when it should have FAILED
- This means the implementation already satisfies this test case
- Likely cause: a previous test drove an implementation that covers this case too

## Your Task
Compare the marked test against the OTHER tests in the file.
Decide: Should we KEEP this test (for documentation/safety) or DISCARD it (truly redundant)?
"""

    try:
        result = await agent.run(prompt)
        decision = result.output
        logger.info(
            f"[ARBITER] Decision: keep={decision.keep_test}, "
            f"confidence={decision.confidence_value}, "
            f"communication={decision.communication_value}"
        )
        logger.info(f"[ARBITER] Reasoning: {decision.reasoning[:200]}...")
        return decision
    except Exception as e:
        logger.error(f"[ARBITER] Error during arbitration: {e}")
        # Default to keep on error
        return ArbiterDecision(
            keep_test=True,
            confidence_value=True,
            communication_value=False,
            reasoning=f"Arbitration error: {str(e)}, defaulting to keep"
        )
