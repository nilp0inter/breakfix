"""Ratchet Red task - Write failing test (RED phase of TDD)."""

from dataclasses import dataclass
from pathlib import Path

from prefect import task
from prefect.logging import get_run_logger

from breakfix.agents import run_ratchet_red
from breakfix.artifacts import ratchet_red_artifacts
from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import UnitWorkItem, TestCase


class RatchetRedError(Exception):
    """Red phase failed."""

    pass


@dataclass
class RatchetRedTaskResult:
    """Result from the Ratchet Red task."""

    test_file_path: str
    pytest_failure: str
    skip_green: bool
    retries: int


@task(persist_result=True, retries=3, retry_delay_seconds=10, name="ratchet-red", log_prints=True)
async def ratchet_red_task(
    unit: UnitWorkItem,
    test_case: TestCase,
    working_directory: str,
    config: BreakFixConfig | None = None,
) -> RatchetRedTaskResult:
    """Write failing test using Tester agent.

    Phase 6 (Atomic Scope): RED phase of TDD - writes a single failing test.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info(f"[RATCHET-RED] Writing test for: {test_case.description[:60]}...")

    production_dir = Path(working_directory) / "production"

    # Convert Pydantic models to dataclasses for backward compatibility
    from dataclasses import dataclass as dc, field

    @dc
    class LegacyUnit:
        name: str
        tests: list = field(default_factory=list)
        code: str = ""
        module_path: str = ""
        line_number: int = 0
        end_line_number: int = 0
        symbol_type: str = ""
        dependencies: list = field(default_factory=list)
        description: str = ""

    @dc
    class LegacyTestCase:
        id: int
        description: str
        test_function_name: str = ""

    legacy_unit = LegacyUnit(
        name=unit.name,
        code=unit.code,
        module_path=unit.module_path,
        line_number=unit.line_number,
        end_line_number=unit.end_line_number,
        symbol_type=unit.symbol_type,
        dependencies=list(unit.dependencies),
        description=unit.description,
    )

    legacy_test_case = LegacyTestCase(
        id=test_case.id,
        description=test_case.description,
        test_function_name=test_case.test_function_name,
    )

    result = await run_ratchet_red(
        unit=legacy_unit,
        test_case=legacy_test_case,
        production_dir=production_dir,
        get_test_inventory_with_errors=config.get_test_inventory_with_errors,
    )

    if not result.success:
        logger.warning(f"[RATCHET-RED] Failed: {result.error}")
        raise RatchetRedError(f"Red phase failed for {unit.name}: {result.error}")

    logger.info(
        f"[RATCHET-RED] Test written successfully: {result.test_file_path} "
        f"(retries: {result.retries})"
    )

    if result.skipped_green:
        logger.info("[RATCHET-RED] Skipping Green phase (arbiter decision)")

    # Create artifacts for UI visibility
    await ratchet_red_artifacts(
        unit_name=unit.name,
        test_id=test_case.id,
        test_description=test_case.description,
        pytest_output=result.pytest_failure,
        retries=result.retries,
        skip_green=result.skipped_green,
    )

    return RatchetRedTaskResult(
        test_file_path=result.test_file_path,
        pytest_failure=result.pytest_failure,
        skip_green=result.skipped_green,
        retries=result.retries,
    )
