"""Crucible flow - Mutation testing and optimization."""

from prefect import flow
from prefect.logging import get_run_logger

from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import UnitWorkItem
from breakfix.tasks import mutation_task, sentinel_task, optimization_task


@flow(
    name="crucible",
    description="Mutation testing and optimization for a unit",
    persist_result=True,
    log_prints=True,
)
async def crucible_flow(
    unit: UnitWorkItem,
    working_directory: str,
    config: BreakFixConfig | None = None,
) -> None:
    """Crucible: Mutation testing + optimization for a unit.

    Phase 7 (Unit Scope): Verifies test robustness and optimizes code.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info(f"[CRUCIBLE] Starting for {unit.name}")

    # Mutation testing loop
    max_iterations = 10  # Safety limit
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        logger.info(f"[CRUCIBLE] Mutation testing iteration {iteration}")

        mutation_result = await mutation_task(
            unit=unit,
            working_directory=working_directory,
            config=config,
        )

        if mutation_result.score == 1.0:
            logger.info(
                f"[CRUCIBLE] Perfect mutation score achieved! "
                f"All {mutation_result.total_mutants} mutants killed."
            )
            break

        logger.info(
            f"[CRUCIBLE] Score: {mutation_result.score:.2%}, "
            f"{len(mutation_result.surviving_mutants)} mutants surviving"
        )

        # Kill surviving mutants with Sentinel
        for mutant in mutation_result.surviving_mutants:
            logger.info(f"[CRUCIBLE] Killing mutant {mutant.id}")
            await sentinel_task(
                unit=unit,
                mutant=mutant,
                working_directory=working_directory,
                config=config,
            )

        logger.info("[CRUCIBLE] Re-running mutation testing to verify...")

    if iteration >= max_iterations:
        logger.warning(
            f"[CRUCIBLE] Max iterations reached ({max_iterations}). "
            f"Some mutants may still be surviving."
        )

    # Optimization phase
    logger.info(f"[CRUCIBLE] Starting optimization for {unit.name}")
    optimization_result = await optimization_task(
        unit=unit,
        working_directory=working_directory,
        config=config,
    )

    # Update unit with optimized code
    unit.code = optimization_result.optimized_code

    logger.info(f"[CRUCIBLE] Complete for {unit.name}")
