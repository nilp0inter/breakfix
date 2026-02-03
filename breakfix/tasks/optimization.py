"""Optimization task - Refactor code for quality while maintaining tests."""

from dataclasses import dataclass

from prefect import task
from prefect.logging import get_run_logger

from breakfix.artifacts import optimization_artifacts
from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import UnitWorkItem


class OptimizationError(Exception):
    """Optimization phase failed."""

    pass


@dataclass
class OptimizationTaskResult:
    """Result from the Optimization task."""

    optimized_code: str


@task(persist_result=True, name="optimization", log_prints=True)
async def optimization_task(
    unit: UnitWorkItem,
    working_directory: str,
    config: BreakFixConfig | None = None,
) -> OptimizationTaskResult:
    """Refactor code for quality while maintaining test coverage.

    Phase 7 (Unit Scope): Crucible - Optimizer improves code quality.

    Note: This is currently a stub implementation that returns the code unchanged.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info(f"[OPTIMIZATION] Optimizing {unit.name}")

    # TODO: Implement actual optimization agent
    # For now, just return the code unchanged
    optimized_code = unit.code

    logger.info(f"[OPTIMIZATION] {unit.name} optimization complete (stub)")

    # Create artifacts for UI visibility
    await optimization_artifacts(unit_name=unit.name, success=True)

    return OptimizationTaskResult(optimized_code=optimized_code)
