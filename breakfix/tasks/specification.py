"""Specification task - Interactive Q&A to capture requirements."""

from prefect import task
from prefect.flow_runs import pause_flow_run
from prefect.input import RunInput
from prefect.logging import get_run_logger
from pydantic import Field
from pydantic_ai.durable_exec.prefect import PrefectAgent

from breakfix.artifacts import specification_artifacts
from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import ProjectState


class UserIdeaInput(RunInput):
    """Input model for initial user idea."""

    idea: str = Field(description="Enter your software idea")


class SpecificationError(Exception):
    """Specification phase failed."""

    pass


@task(persist_result=True, name="specification")
async def specification_task(
    working_directory: str,
    config: BreakFixConfig | None = None,
) -> ProjectState:
    """Interactive Q&A to capture requirements.

    Phase 1: Uses the Analyst agent to conduct Q&A and produce specification.
    Uses Prefect's pause_flow_run for user interaction via PrefectAgent wrapper.

    The Analyst agent's ask_user tool uses pause_flow_run internally.
    PrefectAgent wraps tool calls as Prefect tasks, ensuring pause_flow_run
    runs within the proper flow context.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info("[SPECIFICATION] Phase 1: Specification (Interactive Q&A)")

    # Get initial idea from user via Prefect UI
    logger.info("[SPECIFICATION] Waiting for user idea...")
    user_input = await pause_flow_run(
        wait_for_input=UserIdeaInput,
        timeout=3600,  # 1 hour timeout
    )

    state = ProjectState(
        user_idea=user_input.idea,
        working_directory=working_directory,
    )

    logger.info(f"[SPECIFICATION] Received idea: {user_input.idea[:100]}...")

    # Create analyst agent - the ask_user tool uses pause_flow_run internally
    agent = config.create_analyst()

    # Wrap with PrefectAgent so tool calls become Prefect tasks
    # This ensures pause_flow_run works correctly inside the ask_user tool
    prefect_agent = PrefectAgent(agent)

    # Run the analyst Q&A loop
    result = await prefect_agent.run(state.user_idea)
    analyst_output = result.output

    # Update state with analyst results
    state.spec = analyst_output.specification
    state.fixtures = analyst_output.fixtures
    state.project_metadata = analyst_output.project

    logger.info(f"[SPECIFICATION] Specification complete: {len(state.spec)} chars")
    logger.info(f"[SPECIFICATION] Fixtures: {len(state.fixtures)} defined")

    # Create artifacts for UI visibility
    await specification_artifacts(state)

    return state
