"""Refinement task - Refactor prototype into FCIS architecture."""

from pathlib import Path

from prefect import task
from prefect.logging import get_run_logger

from breakfix.agents import run_refactorer, review_architecture
from breakfix.artifacts import refinement_result_artifact
from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import ProjectState


class RefinementError(Exception):
    """Refinement phase failed."""

    pass


@task(persist_result=True, name="refinement", log_prints=True)
async def refinement_task(
    state: ProjectState,
    config: BreakFixConfig | None = None,
) -> ProjectState:
    """Refactor prototype into Functional Core / Imperative Shell architecture.

    Phase 3: Uses the Refactorer agent to restructure code with FCIS principles.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info("[REFINEMENT] Phase 3: Refinement")

    if state.project_metadata is None:
        raise RefinementError("Project metadata is required for refinement")

    # Create a closure for running E2E tests
    async def run_e2e_test(proto_dir: Path, package_name: str) -> object:
        return await config.run_prototype_e2e_test(proto_dir, package_name)

    result = await run_refactorer(
        working_dir=state.working_directory,
        package_name=state.project_metadata.package_name,
        run_e2e_test=run_e2e_test,
        review_architecture=review_architecture,
    )

    if not result.success:
        raise RefinementError(f"Refinement failed: {result.error}")

    logger.info(f"[REFINEMENT] Refinement completed in {result.iterations} iteration(s)")

    # Update state
    new_state = state.model_copy(deep=True)
    new_state.refined_arch = "FCIS applied"

    # Create artifacts for UI visibility
    await refinement_result_artifact(
        iterations=result.iterations,
        success=True,
    )

    return new_state
