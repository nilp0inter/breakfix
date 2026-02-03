"""Mutation task - Run mutation testing with mutmut."""

from dataclasses import dataclass
from pathlib import Path
from typing import List

from prefect import task
from prefect.logging import get_run_logger

from breakfix.agents import run_mutation_testing, SurvivingMutant
from breakfix.artifacts import mutation_artifacts
from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import UnitWorkItem


class MutationError(Exception):
    """Mutation testing failed."""

    pass


@dataclass
class MutationTaskResult:
    """Result from the Mutation task."""

    score: float
    total_mutants: int
    surviving_mutants: List[SurvivingMutant]


@task(persist_result=True, name="mutation", log_prints=True)
async def mutation_task(
    unit: UnitWorkItem,
    working_directory: str,
    config: BreakFixConfig | None = None,
) -> MutationTaskResult:
    """Run mutation testing to verify test suite completeness.

    Phase 7 (Unit Scope): Crucible - uses mutmut to verify test robustness.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info(f"[MUTATION] Running mutation testing for {unit.name}")

    production_dir = Path(working_directory) / "production"

    result = await run_mutation_testing(
        production_dir=production_dir,
        unit_fqn=unit.name,
        module_path=unit.module_path,
        start_line=unit.line_number,
        end_line=unit.end_line_number,
    )

    if not result.success:
        raise MutationError(f"Mutation testing failed: {result.error}")

    if result.score < 1.0:
        logger.warning(
            f"[MUTATION] Mutation score {result.score:.2%}. "
            f"{len(result.surviving_mutants)} mutants survived "
            f"out of {result.total_mutants}."
        )
    else:
        logger.info(
            f"[MUTATION] Perfect mutation score! "
            f"All {result.total_mutants} mutants killed."
        )

    # Create artifacts for UI visibility
    await mutation_artifacts(
        unit_name=unit.name,
        score=result.score,
        total_mutants=result.total_mutants,
        surviving_mutants=result.surviving_mutants,
    )

    return MutationTaskResult(
        score=result.score,
        total_mutants=result.total_mutants,
        surviving_mutants=result.surviving_mutants,
    )
