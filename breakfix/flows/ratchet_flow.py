"""Ratchet flow - TDD Red-Green cycle per test."""

from prefect import flow
from prefect.logging import get_run_logger

from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import UnitWorkItem, TestCase
from breakfix.tasks import ratchet_red_task, ratchet_green_task


@flow(
    name="ratchet-cycle",
    description="TDD Red-Green cycle for a single test case",
    persist_result=True,
    log_prints=True,
)
async def ratchet_cycle_flow(
    unit: UnitWorkItem,
    test_case: TestCase,
    working_directory: str,
    config: BreakFixConfig | None = None,
) -> None:
    """Ratchet cycle: Red-Green TDD for a single test case.

    Phase 6 (Atomic Scope): Executes one iteration of the TDD cycle.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info(f"[RATCHET] Starting cycle for test: {test_case.description[:50]}...")

    # RED phase: Write failing test
    red_result = await ratchet_red_task(
        unit=unit,
        test_case=test_case,
        working_directory=working_directory,
        config=config,
    )

    # Check if Green phase should be skipped (arbiter decision)
    if red_result.skip_green:
        logger.info("[RATCHET] Green phase skipped (arbiter decision)")
        return

    # GREEN phase: Write passing implementation
    await ratchet_green_task(
        unit=unit,
        test_case=test_case,
        pytest_failure=red_result.pytest_failure,
        working_directory=working_directory,
        config=config,
    )

    logger.info(f"[RATCHET] Cycle complete for: {test_case.description[:50]}...")
