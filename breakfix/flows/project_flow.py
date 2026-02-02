"""Project flow - Main BreakFix pipeline."""

from prefect import flow
from prefect.logging import get_run_logger

from breakfix.blocks import BreakFixConfig, get_config
from breakfix.tasks import (
    specification_task,
    e2e_builder_task,
    scaffold_task,
    prototyping_task,
    refinement_task,
    distillation_task,
)
from breakfix.flows.unit_flow import oracle_and_ratchet_flow


@flow(
    name="breakfix-project",
    description="Transform user idea into tested Python software",
    persist_result=True,
)
async def breakfix_project_flow(
    working_directory: str,
    config: BreakFixConfig | None = None,
) -> str:
    """Main BreakFix pipeline - executes once per project idea.

    Orchestrates all phases from specification through TDD reconstruction.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info("[PROJECT] Starting BreakFix pipeline")
    logger.info(f"[PROJECT] Working directory: {working_directory}")

    # Phase 1: Specification (interactive Q&A)
    state = await specification_task(working_directory, config=config)

    # Phase 1a: E2E Test Builder
    state = await e2e_builder_task(state, config=config)

    # Phase 1b: Scaffolding
    state = await scaffold_task(state, config=config)

    # Phase 2: Prototyping
    state = await prototyping_task(state, config=config)

    # Phase 3: Refinement
    state = await refinement_task(state, config=config)

    # Phase 4: Distillation
    state = await distillation_task(state, config=config)

    # Phase 5-7: Oracle + Ratchet + Crucible (per unit)
    total_units = len(state.unit_queue)
    for i, unit in enumerate(state.unit_queue):
        logger.info(f"[PROJECT] Processing unit {i + 1}/{total_units}: {unit.name}")

        # Skip non-testable units
        if unit.symbol_type not in ("function", "class"):
            logger.info(
                f"[PROJECT] Skipped {unit.name} (symbol_type={unit.symbol_type})"
            )
            state.finished_units.append(f"{unit.name} (Skipped - {unit.symbol_type})")
            continue

        result = await oracle_and_ratchet_flow(
            unit=unit,
            working_directory=state.working_directory,
            config=config,
        )
        state.finished_units.append(result)

    logger.info(f"[PROJECT] Pipeline complete. Units processed: {len(state.finished_units)}")

    return f"Project Complete. Units: {state.finished_units}"
