"""Unit flow - Oracle + Ratchet orchestration per unit."""

from prefect import flow
from prefect.logging import get_run_logger

from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import UnitWorkItem
from breakfix.tasks import oracle_task
from breakfix.flows.ratchet_flow import ratchet_cycle_flow
from breakfix.flows.crucible_flow import crucible_flow


@flow(
    name="oracle-and-ratchet",
    description="Process a single unit through Oracle + TDD cycles",
    persist_result=True,
    log_prints=True,
)
async def oracle_and_ratchet_flow(
    unit: UnitWorkItem,
    working_directory: str,
    config: BreakFixConfig | None = None,
) -> str:
    """Inner flow: runs once per unit.

    Orchestrates Oracle (test spec generation), Ratchet (TDD cycles),
    and Crucible (mutation testing + optimization) for a single unit.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info(f"[UNIT] Starting unit flow for: {unit.name}")

    # Skip non-testable units
    if unit.symbol_type not in ("function", "class"):
        logger.info(f"[UNIT] Skipped {unit.name} (symbol_type={unit.symbol_type})")
        return f"{unit.name} (Skipped - {unit.symbol_type})"

    # Generate test specs via Oracle
    oracle_result = await oracle_task(unit, config=config)
    unit.description = oracle_result.description
    unit.tests = oracle_result.test_cases

    logger.info(f"[UNIT] Oracle generated {len(unit.tests)} test cases for {unit.name}")

    # Ratchet cycle for each test case
    for i, test_case in enumerate(unit.tests):
        logger.info(
            f"[UNIT] Ratchet cycle {i + 1}/{len(unit.tests)} for: "
            f"{test_case.description[:50]}..."
        )
        await ratchet_cycle_flow(
            unit=unit,
            test_case=test_case,
            working_directory=working_directory,
            config=config,
        )

    logger.info(f"[UNIT] All {len(unit.tests)} tests completed for {unit.name}")

    # Crucible cycle for hardening
    logger.info(f"[UNIT] Starting Crucible for {unit.name}")
    await crucible_flow(
        unit=unit,
        working_directory=working_directory,
        config=config,
    )

    logger.info(f"[UNIT] Unit {unit.name} completed successfully")

    return f"{unit.name} (Verified)"
