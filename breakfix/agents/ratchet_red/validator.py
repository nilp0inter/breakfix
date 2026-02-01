"""Test validator using Pydantic AI to verify test adheres to specification."""
import logging
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent


logger = logging.getLogger(__name__)


class ValidationResult(BaseModel):
    """Result from test validation."""
    is_valid: bool = Field(
        ...,
        description="True if test adheres to specification, False otherwise"
    )
    reason: str = Field(
        default="",
        description="Reason for rejection (only populated if is_valid=False)"
    )


VALIDATOR_SYSTEM_PROMPT = """You are a TDD test validator. Your job is to verify that a test
correctly implements a given test specification.

Evaluate whether the test:
1. Tests the exact scenario described in the specification
2. Uses appropriate inputs as described in the specification
3. Checks for the expected outcome as described
4. Is a single, focused test (not multiple tests bundled together)
5. Imports and calls the correct function/class being tested

Respond with:
- is_valid: True if the test correctly implements the specification
- reason: If is_valid=False, provide a clear, actionable explanation of what's wrong

Be strict but fair. The test should match the specification's intent, not necessarily
use exact same wording. Focus on whether the test will verify the specified behavior.
"""


def create_test_validator(model: str = "openai:gpt-5") -> Agent[None, ValidationResult]:
    """Create test validator agent."""
    return Agent(
        model,
        output_type=ValidationResult,
        system_prompt=VALIDATOR_SYSTEM_PROMPT,
    )


async def validate_test(
    unit_name: str,
    unit_code: str,
    test_spec: str,
    test_file_path: str,
    tests_dir: Path,
    model: str = "openai:gpt-5",
) -> ValidationResult:
    """
    Validate that a new test adheres to its specification.

    Args:
        unit_name: Name of the unit being tested (e.g., "pkg.core.calculate")
        unit_code: Source code of the unit (signature/stub)
        test_spec: The test case description from Oracle
        test_file_path: pytest node ID (e.g., "tests/test_core.py::test_calculate_positive")
        tests_dir: Tests directory path
        model: LLM model to use

    Returns:
        ValidationResult with is_valid and reason
    """
    # Extract file path from pytest node ID (e.g., "tests/test_core.py::test_func")
    if "::" in test_file_path:
        file_part, test_name = test_file_path.split("::", 1)
    else:
        file_part = test_file_path
        test_name = "unknown"

    # Read the test file
    test_file = tests_dir.parent / file_part
    if not test_file.exists():
        logger.error(f"[VALIDATOR] Test file not found: {test_file}")
        return ValidationResult(
            is_valid=False,
            reason=f"Test file not found: {test_file}"
        )

    test_content = test_file.read_text()
    logger.info(f"[VALIDATOR] Validating test '{test_name}' from {test_file}")

    agent = create_test_validator(model)

    prompt = f"""Validate whether this test correctly implements the specification.

## Unit Being Tested
Name: {unit_name}

Signature/Stub:
```python
{unit_code}
```

## Test Specification (from Oracle)
{test_spec}

## Test File Content ({test_file_path})
```python
{test_content}
```

## Question
Does the test `{test_name}` correctly implement the test specification above?

Consider:
- Does it test the scenario described?
- Does it use the inputs described?
- Does it check for the expected outcome?
- Is it a single focused test?
"""

    try:
        result = await agent.run(prompt)
        validation = result.output
        logger.info(f"[VALIDATOR] Result: is_valid={validation.is_valid}, reason={validation.reason[:100] if validation.reason else 'N/A'}")
        return validation
    except Exception as e:
        logger.error(f"[VALIDATOR] Error during validation: {e}")
        return ValidationResult(
            is_valid=False,
            reason=f"Validation error: {str(e)}"
        )
