"""Prototyping task - Create initial prototype implementation."""

from pathlib import Path

from prefect import task
from prefect.logging import get_run_logger

from breakfix.agents import run_prototyper
from breakfix.artifacts import prototyping_result_artifact
from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import ProjectState


class PrototypingError(Exception):
    """Prototyping phase failed."""

    pass


@task(persist_result=True, name="prototyping", log_prints=True)
async def prototyping_task(
    state: ProjectState,
    config: BreakFixConfig | None = None,
) -> ProjectState:
    """Create initial prototype implementation.

    Phase 2: Uses the Prototyper agent to implement a working prototype
    with feedback loop against E2E tests.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info("[PROTOTYPING] Phase 2: Prototyping")

    if state.project_metadata is None:
        raise PrototypingError("Project metadata is required for prototyping")

    # Create a closure for running E2E tests
    async def run_e2e_test(proto_dir: Path) -> object:
        return await config.run_prototype_e2e_test(
            proto_dir, state.project_metadata.package_name
        )

    result = await run_prototyper(
        working_dir=state.working_directory,
        spec=state.spec,
        fixtures=state.fixtures,
        package_name=state.project_metadata.package_name,
        run_e2e_test=run_e2e_test,
        interface_description=state.interface_description,
    )

    if not result.success:
        # Create artifact even on failure
        await prototyping_result_artifact(
            iterations=result.iterations,
            success=False,
            error=result.error,
        )
        raise PrototypingError(
            f"Prototyping failed after {result.iterations} iterations: {result.error}"
        )

    logger.info(f"[PROTOTYPING] Prototype completed in {result.iterations} iteration(s)")

    # Create artifacts for UI visibility
    await prototyping_result_artifact(
        iterations=result.iterations,
        success=True,
    )

    return state
