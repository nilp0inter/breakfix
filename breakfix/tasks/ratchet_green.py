"""Ratchet Green task - Write passing implementation (GREEN phase of TDD)."""

from dataclasses import dataclass
from pathlib import Path

from prefect import task
from prefect.logging import get_run_logger

from breakfix.agents import run_ratchet_green
from breakfix.agents.ratchet_red.agent import _calculate_test_file_path
from breakfix.artifacts import ratchet_green_artifacts
from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import UnitWorkItem, TestCase


class RatchetGreenError(Exception):
    """Green phase failed."""

    pass


@dataclass
class RatchetGreenTaskResult:
    """Result from the Ratchet Green task."""

    retries: int


@task(persist_result=True, retries=3, retry_delay_seconds=10, name="ratchet-green", log_prints=True)
async def ratchet_green_task(
    unit: UnitWorkItem,
    test_case: TestCase,
    pytest_failure: str,
    working_directory: str,
    config: BreakFixConfig | None = None,
) -> RatchetGreenTaskResult:
    """Write passing implementation using Developer agent.

    Phase 6 (Atomic Scope): GREEN phase of TDD - implements code to pass the test.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info(f"[RATCHET-GREEN] Implementing code for: {test_case.description[:60]}...")

    production_dir = Path(working_directory) / "production"
    test_file_path = _calculate_test_file_path(unit.name)

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

    result = await run_ratchet_green(
        unit=legacy_unit,
        test_case=legacy_test_case,
        test_file_path=test_file_path,
        production_dir=production_dir,
        working_dir=Path(working_directory),
        initial_failure=pytest_failure,
    )

    if not result.success:
        logger.warning(f"[RATCHET-GREEN] Failed: {result.error}")
        raise RatchetGreenError(f"Green phase failed for {unit.name}: {result.error}")

    logger.info(
        f"[RATCHET-GREEN] Implementation complete, all tests passing "
        f"(retries: {result.retries})"
    )

    # Create artifacts for UI visibility
    await ratchet_green_artifacts(
        unit_name=unit.name,
        test_id=test_case.id,
        retries=result.retries,
        success=True,
    )

    return RatchetGreenTaskResult(retries=result.retries)
