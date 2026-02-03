"""E2E Builder task - Create end-to-end test harness."""

from pathlib import Path

from prefect import task
from prefect.logging import get_run_logger

from breakfix.agents import run_e2e_builder, analyze_interface
from breakfix.artifacts import e2e_builder_artifacts
from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import ProjectState


class E2EBuilderError(Exception):
    """E2E test builder failed."""

    pass


def _format_interface_description(interface_desc) -> str:
    """Format InterfaceDescription into a readable string for the prototyper."""
    return f"""Summary: {interface_desc.summary}
Input method: {interface_desc.input_method}
Output method: {interface_desc.output_method}
Input format: {interface_desc.input_format}
Output format: {interface_desc.output_format}
Protocol details: {interface_desc.protocol_details}
Invocation: {interface_desc.invocation}
Example interaction:
{interface_desc.example_interaction}"""


@task(persist_result=True, name="e2e-builder", log_prints=True)
async def e2e_builder_task(
    state: ProjectState,
    config: BreakFixConfig | None = None,
) -> ProjectState:
    """Create E2E test harness before scaffolding.

    Phase 1a: Creates e2e-tests/ directory with run_tests.py and mock_program.py.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info("[E2E-BUILDER] Phase 1a: E2E Test Builder")

    result = await run_e2e_builder(
        working_dir=state.working_directory,
        fixtures=state.fixtures,
        spec=state.spec,
    )

    if not result.success:
        raise E2EBuilderError(f"E2E builder failed: {result.error}")

    # Verify the E2E test harness works with the mock program
    logger.info("[E2E-BUILDER] Verifying E2E test harness")
    e2e_dir = Path(state.working_directory) / "e2e-tests"
    verification_result = await config.run_e2e_verification(e2e_dir)

    if not verification_result.success:
        raise E2EBuilderError(f"E2E verification failed: {verification_result.error}")

    # Analyze mock_program.py interface
    logger.info("[E2E-BUILDER] Analyzing mock program interface")
    mock_program_path = e2e_dir / "mock_program.py"
    mock_program_code = mock_program_path.read_text()
    interface_desc = await analyze_interface(mock_program_code)

    # Update state with interface description
    new_state = state.model_copy(deep=True)
    new_state.interface_description = _format_interface_description(interface_desc)

    logger.info("[E2E-BUILDER] E2E test harness created and verified")

    # Create artifacts for UI visibility
    await e2e_builder_artifacts(
        interface_description=new_state.interface_description,
        verification_passed=True,
    )

    return new_state
