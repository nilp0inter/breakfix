"""Distillation task - Decompose refined prototype into atomic units."""

from pathlib import Path

from prefect import task
from prefect.logging import get_run_logger

from breakfix.artifacts import distillation_artifacts
from breakfix.blocks import BreakFixConfig, get_config
from breakfix.distiller import run_distiller
from breakfix.workspace import copy_prototype_to_production, cleanup_production_code
from breakfix.state import ProjectState, UnitWorkItem


class DistillationError(Exception):
    """Distillation phase failed."""

    pass


@task(persist_result=True, name="distillation")
async def distillation_task(
    state: ProjectState,
    config: BreakFixConfig | None = None,
) -> ProjectState:
    """Decompose refined prototype into atomic units.

    Phase 4: Uses pydeps and AST analysis to extract units for TDD reconstruction.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info("[DISTILLATION] Phase 4: Distillation")

    if state.project_metadata is None:
        raise DistillationError("Project metadata is required for distillation")

    prod_dir = Path(state.working_directory) / "production"

    # Step 1: Copy prototype to production for ratchet cycle
    logger.info("[DISTILLATION] Copying prototype to production workspace")
    copy_result = await copy_prototype_to_production(Path(state.working_directory))

    if not copy_result.success:
        raise DistillationError(
            f"Failed to copy prototype to production: {copy_result.error}"
        )

    # Step 2: Run distiller to analyze production
    result = await run_distiller(
        proto_dir=prod_dir,
        package_name=state.project_metadata.package_name,
    )

    if not result.success:
        raise DistillationError(f"Distillation failed: {result.error}")

    logger.info(f"[DISTILLATION] Distilled {len(result.units)} units")

    # Convert distiller units to our Pydantic models
    units = [
        UnitWorkItem(
            name=u.name,
            code=u.code,
            module_path=u.module_path,
            line_number=u.line_number,
            end_line_number=u.end_line_number,
            symbol_type=u.symbol_type,
            dependencies=u.dependencies,
        )
        for u in result.units
    ]

    # Step 3: Clean up production code for TDD
    logger.info("[DISTILLATION] Cleaning up production code for TDD")
    cleanup_result = await cleanup_production_code(unit_queue=units)

    if not cleanup_result.success:
        raise DistillationError(f"Cleanup failed: {cleanup_result.error}")

    logger.info(
        f"[DISTILLATION] Stubbed {cleanup_result.functions_stubbed} functions "
        f"in {cleanup_result.files_modified} files"
    )

    # Step 4: Filter unit_queue to only include units from stubbed files
    def is_tdd_target(unit: UnitWorkItem) -> bool:
        return unit.module_path.endswith("shell.py") or unit.module_path.endswith(
            "core.py"
        )

    all_units = len(units)
    tdd_units = [u for u in units if is_tdd_target(u)]
    logger.info(
        f"[DISTILLATION] Filtered to {len(tdd_units)} TDD target units "
        f"(from {all_units} total)"
    )

    # Update state
    new_state = state.model_copy(deep=True)
    new_state.unit_queue = tdd_units

    # Create artifacts for UI visibility
    await distillation_artifacts(
        unit_queue=tdd_units,
        total_units=all_units,
        tdd_targets=len(tdd_units),
        functions_stubbed=cleanup_result.functions_stubbed,
        files_modified=cleanup_result.files_modified,
    )

    return new_state
