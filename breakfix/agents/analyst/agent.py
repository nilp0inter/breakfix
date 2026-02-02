from typing import Any, List

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, Tool
from prefect.flow_runs import pause_flow_run
from prefect.input import RunInput
from prefect.logging import get_run_logger


class TestFixture(BaseModel):
    """A test fixture representing a specific test scenario."""
    name: str = Field(description="A short descriptive name for the fixture")
    description: str = Field(description="What this fixture tests")
    input_data: Any = Field(description="The input data for the test")
    expected_output: Any = Field(description="The expected output/behavior")


class ProjectMetadata(BaseModel):
    """Metadata for PyScaffold project initialization."""
    project_name: str = Field(description="Installable name (pip install name, e.g., 'my-project')")
    package_name: str = Field(description="Package name for imports (e.g., 'my_project')")
    description: str = Field(max_length=200, description="Short project description")
    license: str = Field(default="MIT", description="License (MIT, Apache-2.0, GPL-3.0-only, etc.)")
    url: str = Field(default="", description="Main project URL (optional)")
    github_actions: bool = Field(default=False, description="Whether to add GitHub Actions CI config")


class AnalystOutput(BaseModel):
    """Output from the Analyst agent containing specification, test fixtures, and project metadata."""
    specification: str = Field(
        min_length=100,
        description="A detailed software specification derived from the user's idea"
    )
    fixtures: List[TestFixture] = Field(
        min_length=3,
        description="Test fixtures covering happy path, edge cases, and error cases"
    )
    project: ProjectMetadata = Field(
        description="Project metadata for PyScaffold initialization"
    )


class ClarificationInput(RunInput):
    """Input model for analyst Q&A responses via Prefect UI."""
    answer: str = Field(description="Your response to the question")


ANALYST_SYSTEM_PROMPT = """You are a Requirements Analyst conducting a structured interview to transform
a vague software idea into a detailed specification with test fixtures.

## Interview Strategy (Top-Down Tree Descent)
1. **Broad Understanding**: Start with the core problem, target users, main goal
2. **Project Identity**: Gather project naming and metadata:
   - What should the project be called? (for pip install, e.g., 'my-project')
   - What should the Python package name be? (for imports, e.g., 'my_project')
   - Brief one-line description of the project
   - Preferred license (MIT, Apache-2.0, GPL-3.0-only, etc.) - default to MIT if unsure
   - Project URL if any (optional)
   - Whether GitHub Actions CI is needed
3. **Feature Exploration**: Identify key features and their expected behaviors
4. **Edge Cases**: Probe boundary conditions and unusual inputs
5. **Error Handling**: Understand what can go wrong and how to handle it
6. **Validation**: Confirm critical assumptions before finalizing

## Your Task
Given the user's idea and conversation history:
- Ask ONE focused clarifying question at a time using the ask_user tool
- Early in the interview, gather project identity information (name, package name, description, license)
- Each question should help inform either project metadata or a specific test fixture
- When you have enough detail (typically 5-8 exchanges), produce the final output

## Final Output
When ready, produce:
1. A detailed specification (min 100 chars) with purpose, inputs/outputs, constraints
2. At least 3 test fixtures:
   - Happy path: normal successful use case
   - Edge case: boundary condition
   - Error case: invalid input or failure scenario
3. Project metadata:
   - project_name: installable name (pip install name, e.g., 'my-project')
   - package_name: Python package name for imports (e.g., 'my_project')
   - description: short project description (max 200 chars)
   - license: license type (default: MIT)
   - url: project URL (optional, can be empty)
   - github_actions: whether to add GitHub Actions CI config (default: false)

Base everything on the actual Q&A - do not invent requirements not discussed."""


def create_analyst(
    model: str = "openai:gpt-5-mini",
) -> Agent[None, AnalystOutput]:
    """
    Create the Analyst agent with ask_user tool.

    The ask_user tool uses Prefect's pause_flow_run to get input from the user
    via the Prefect UI. This requires the agent to be wrapped with PrefectAgent
    so that tool calls run as Prefect tasks.

    Args:
        model: The model to use

    Returns:
        An Agent that can be used with PrefectAgent for interactive Q&A
    """
    async def ask_user(ctx: RunContext[None], question: str) -> str:
        """Ask the user a clarifying question via Prefect UI."""
        logger = get_run_logger()
        logger.info(f"[ANALYST] Question: {question}")

        response = await pause_flow_run(
            wait_for_input=ClarificationInput,
            timeout=3600,  # 1 hour timeout
        )
        return response.answer

    return Agent(
        model,
        output_type=AnalystOutput,
        system_prompt=ANALYST_SYSTEM_PROMPT,
        tools=[Tool(ask_user)],
        name="analyst",  # Required for PrefectAgent
    )
