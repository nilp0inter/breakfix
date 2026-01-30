from typing import Any, Callable, List

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, Tool


class TestFixture(BaseModel):
    """A test fixture representing a specific test scenario."""
    name: str = Field(description="A short descriptive name for the fixture")
    description: str = Field(description="What this fixture tests")
    input_data: Any = Field(description="The input data for the test")
    expected_output: Any = Field(description="The expected output/behavior")


class AnalystOutput(BaseModel):
    """Output from the Analyst agent containing specification and test fixtures."""
    specification: str = Field(
        min_length=100,
        description="A detailed software specification derived from the user's idea"
    )
    fixtures: List[TestFixture] = Field(
        min_length=3,
        description="Test fixtures covering happy path, edge cases, and error cases"
    )


ANALYST_SYSTEM_PROMPT = """You are a Requirements Analyst conducting a structured interview to transform
a vague software idea into a detailed specification with test fixtures.

## Interview Strategy (Top-Down Tree Descent)
1. **Broad Understanding**: Start with the core problem, target users, main goal
2. **Feature Exploration**: Identify key features and their expected behaviors
3. **Edge Cases**: Probe boundary conditions and unusual inputs
4. **Error Handling**: Understand what can go wrong and how to handle it
5. **Validation**: Confirm critical assumptions before finalizing

## Your Task
Given the user's idea and conversation history:
- Ask ONE focused clarifying question at a time using the ask_user tool
- Each question should help inform a specific test fixture
- When you have enough detail (typically 5-8 exchanges), produce the final output

## Final Output
When ready, produce:
1. A detailed specification (min 100 chars) with purpose, inputs/outputs, constraints
2. At least 3 test fixtures:
   - Happy path: normal successful use case
   - Edge case: boundary condition
   - Error case: invalid input or failure scenario

Base everything on the actual Q&A - do not invent requirements not discussed."""


def create_analyst(
    model: str = "openai:gpt-5-mini",
    input_fn: Callable[[str], str] = input
) -> Agent[None, AnalystOutput]:
    """
    Create the Analyst agent with ask_user tool.

    Args:
        model: The model to use
        input_fn: Function to get user input (injectable for testing)

    Returns:
        An Agent that can be used with iter() for interactive Q&A
    """
    async def ask_user(ctx: RunContext[None], question: str) -> str:
        """Ask the user a clarifying question about their requirements."""
        return input_fn(f"\n{question}\n> ")

    return Agent(
        model,
        output_type=AnalystOutput,
        system_prompt=ANALYST_SYSTEM_PROMPT,
        tools=[Tool(ask_user)],
    )
