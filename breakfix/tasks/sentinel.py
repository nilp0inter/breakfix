"""Sentinel task - Kill surviving mutants by writing targeted tests."""

from dataclasses import dataclass
from pathlib import Path

from prefect import task
from prefect.logging import get_run_logger

from breakfix.agents import run_sentinel, verify_mutant_killed, SurvivingMutant
from breakfix.artifacts import sentinel_artifacts
from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import UnitWorkItem


class SentinelError(Exception):
    """Sentinel phase failed."""

    pass


@dataclass
class SentinelTaskResult:
    """Result from the Sentinel task."""

    mutant_killed: bool
    mutant_id: int


@task(persist_result=True, retries=2, retry_delay_seconds=10, name="sentinel")
async def sentinel_task(
    unit: UnitWorkItem,
    mutant: SurvivingMutant,
    working_directory: str,
    config: BreakFixConfig | None = None,
) -> SentinelTaskResult:
    """Kill a surviving mutant by writing a targeted test.

    Phase 7 (Unit Scope): Crucible - Sentinel writes tests to kill mutants.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info(f"[SENTINEL] Targeting mutant {mutant.id}")

    production_dir = Path(working_directory) / "production"

    # Convert Pydantic model to dataclass for backward compatibility
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

    result = await run_sentinel(
        unit=legacy_unit,
        mutant=mutant,
        production_dir=production_dir,
    )

    if not result.success:
        raise SentinelError(
            f"Failed to write test for mutant {mutant.id}: {result.error}"
        )

    # Verify the test actually kills the mutant
    logger.info(f"[SENTINEL] Verifying mutant {mutant.id} is killed...")
    verification = await verify_mutant_killed(
        production_dir=production_dir,
        unit_fqn=unit.name,
        mutant_id=mutant.id,
        module_path=unit.module_path,
        start_line=unit.line_number,
        end_line=unit.end_line_number,
    )

    if not verification.killed:
        raise SentinelError(
            f"Sentinel test failed to kill mutant {mutant.id}. "
            f"Still surviving after new test added."
        )

    logger.info(f"[SENTINEL] Mutant {mutant.id} killed!")

    # Create artifacts for UI visibility
    await sentinel_artifacts(
        unit_name=unit.name,
        mutant_id=str(mutant.id),
        mutant_killed=True,
    )

    return SentinelTaskResult(
        mutant_killed=True,
        mutant_id=mutant.id,
    )
