"""Oracle agent - generates test descriptions from code."""
from dataclasses import dataclass, field
from typing import List, TYPE_CHECKING

from pydantic import BaseModel, Field
from pydantic_ai import Agent

if TYPE_CHECKING:
    from breakfix.nodes import UnitWorkItem, TestCase


class TestCaseDescription(BaseModel):
    """A single test case description - very specific and precise."""
    test_function_name: str = Field(
        ...,
        description="The pytest test function name (e.g., 'test_calculate_with_empty_list')"
    )
    scenario: str = Field(
        ...,
        description="The exact scenario/condition being tested"
    )
    input_description: str = Field(
        ...,
        description="The specific input values or state for this test"
    )
    expected_outcome: str = Field(
        ...,
        description="The expected outcome or behavior"
    )


class OracleOutput(BaseModel):
    """Output from Oracle agent."""
    description: str = Field(
        ...,
        min_length=50,
        description="Exhaustive textual description of what this function does"
    )
    test_cases: List[TestCaseDescription] = Field(
        ...,
        min_length=1,
        description="Precise test case specifications"
    )


@dataclass
class OracleResult:
    """Result from running Oracle on a single unit."""
    success: bool
    test_cases: List["TestCase"] = field(default_factory=list)
    description: str = ""
    error: str = ""


ORACLE_SYSTEM_PROMPT = """You are a TDD test oracle. Given a Python function's source code,
you must provide:

1. An EXHAUSTIVE DESCRIPTION of what the function does:
   - Its purpose and high-level behavior
   - Each input parameter and its constraints/valid values
   - The return value and all possible outcomes
   - Any side effects (file I/O, state changes, network calls)
   - Error conditions and how they're handled

2. PRECISE TEST CASE SPECIFICATIONS:
   The minimal number of tests cases to exhaustively test all the execution paths.

   For each test case, specify exactly:
   - test_function_name: A valid pytest function name (must start with "test_", use snake_case)
   - scenario: The exact condition being tested (e.g., "empty list input")
   - input_description: Specific input values (e.g., "items=[], discount=0.0")
   - expected_outcome: What should happen (e.g., "returns Decimal('0.00')")

IMPORTANT for test_function_name:
- Must start with "test_"
- Use snake_case (lowercase with underscores)
- Be descriptive but concise
- Include the function name being tested
- Example: "test_calculate_total_with_empty_list"

Focus on:
- Edge cases (empty input, None, boundary values, zero, negative)
- Normal operation with typical inputs
- Error handling (invalid types, out-of-range values)
- For pure functions: precise input/output relationships
- For I/O functions: side effects and state changes

Example for `calculate_total(items: List[Item], discount: float) -> Decimal`:

description: "Calculates the total price of a list of items with an optional
discount. Takes a list of Item objects (each with a 'price' Decimal attribute)
and a discount float between 0.0 and 1.0. Returns the sum of all item prices
multiplied by (1 - discount). Raises ValueError if discount is outside valid
range. Raises TypeError if items is None."

test_cases:
- test_function_name: "test_calculate_total_with_empty_list"
  scenario: "Empty list input"
  input_description: "items=[], discount=0.0"
  expected_outcome: "Returns Decimal('0.00')"

- test_function_name: "test_calculate_total_single_item_no_discount"
  scenario: "Single item with no discount"
  input_description: "items=[Item(price=Decimal('10.00'))], discount=0.0"
  expected_outcome: "Returns Decimal('10.00')"

- test_function_name: "test_calculate_total_multiple_items_with_discount"
  scenario: "Multiple items with 10% discount"
  input_description: "items=[Item(price=Decimal('10.00')), Item(price=Decimal('20.00'))], discount=0.1"
  expected_outcome: "Returns Decimal('27.00')"

- test_function_name: "test_calculate_total_full_discount"
  scenario: "Discount at boundary (100%)"
  input_description: "items=[Item(price=Decimal('50.00'))], discount=1.0"
  expected_outcome: "Returns Decimal('0.00')"

- test_function_name: "test_calculate_total_raises_on_negative_discount"
  scenario: "Invalid discount (negative)"
  input_description: "items=[], discount=-0.1"
  expected_outcome: "Raises ValueError with message about invalid discount"

- test_function_name: "test_calculate_total_raises_on_none_items"
  scenario: "None items list"
  input_description: "items=None, discount=0.0"
  expected_outcome: "Raises TypeError"
"""


def create_oracle(model: str = "openai:gpt-5") -> Agent[None, OracleOutput]:
    """Create Oracle agent for generating test descriptions."""
    return Agent(
        model,
        output_type=OracleOutput,
        system_prompt=ORACLE_SYSTEM_PROMPT,
    )


async def run_oracle(
    unit: "UnitWorkItem",
    model: str = "openai:gpt-5",
) -> OracleResult:
    """
    Analyze a unit's code and generate test case descriptions.

    Args:
        unit: The UnitWorkItem to analyze
        model: LLM model to use

    Returns:
        OracleResult with populated test_cases list and description
    """
    # Import here to avoid circular imports
    from breakfix.nodes import TestCase

    # Skip non-function units (constants, imports don't need tests)
    if unit.symbol_type not in ("function", "class"):
        return OracleResult(success=True, test_cases=[])

    try:
        agent = create_oracle(model)

        prompt = f"""Analyze this Python {unit.symbol_type} and generate test cases:

Name: {unit.name}
Dependencies: {', '.join(unit.dependencies) if unit.dependencies else 'None'}

```python
{unit.code}
```

Generate specific test case descriptions for this code."""

        result = await agent.run(prompt)
        output = result.output

        # Convert to TestCase objects with sequential IDs
        # Format the structured description into a precise string
        test_cases = [
            TestCase(
                id=i + 1,
                description=f"Scenario: {tc.scenario}\n"
                           f"Input: {tc.input_description}\n"
                           f"Expected: {tc.expected_outcome}",
                test_function_name=tc.test_function_name,
            )
            for i, tc in enumerate(output.test_cases)
        ]

        return OracleResult(
            success=True,
            test_cases=test_cases,
            description=output.description,
        )

    except Exception as e:
        return OracleResult(success=False, error=str(e))
