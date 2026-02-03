"""Oracle task - Generate test descriptions for a unit."""

from dataclasses import dataclass
from typing import List

from prefect import task
from prefect.logging import get_run_logger

from breakfix.agents import run_oracle
from breakfix.artifacts import oracle_artifacts
from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import UnitWorkItem, TestCase


class OracleError(Exception):
    """Oracle phase failed."""

    pass


@dataclass
class OracleTaskResult:
    """Result from the Oracle task."""

    description: str
    test_cases: List[TestCase]


@task(persist_result=True, name="oracle", log_prints=True)
async def oracle_task(
    unit: UnitWorkItem,
    config: BreakFixConfig | None = None,
) -> OracleTaskResult:
    """Generate test descriptions for a unit.

    Phase 5 (Unit Scope): Uses the Oracle agent to analyze unit code
    and generate exhaustive test case specifications.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info(f"[ORACLE] Generating test specs for: {unit.name}")

    # Convert Pydantic model to dataclass for backward compatibility with agent
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

    result = await run_oracle(legacy_unit)

    if not result.success:
        raise OracleError(f"Oracle failed for {unit.name}: {result.error}")

    # Log Oracle output
    logger.info(f"[ORACLE] {unit.name} - Description:")
    for line in result.description.split("\n"):
        logger.info(f"[ORACLE]   {line}")
    logger.info(f"[ORACLE] {unit.name} - Test cases ({len(result.test_cases)}):")
    for tc in result.test_cases:
        logger.info(f"[ORACLE]   [{tc.id}] {tc.description.replace(chr(10), ' | ')}")

    # Convert test cases to our Pydantic models
    test_cases = [
        TestCase(
            id=tc.id,
            description=tc.description,
            test_function_name=getattr(tc, "test_function_name", ""),
        )
        for tc in result.test_cases
    ]

    # Create artifacts for UI visibility
    await oracle_artifacts(
        unit_name=unit.name,
        description=result.description,
        test_cases=test_cases,
    )

    return OracleTaskResult(
        description=result.description,
        test_cases=test_cases,
    )
