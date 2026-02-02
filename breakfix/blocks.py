"""Prefect Blocks for BreakFix configuration and agent factories."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Set

from prefect import task
from prefect.blocks.core import Block
from prefect.logging import get_run_logger
from pydantic import Field


@dataclass
class ScaffoldResult:
    """Result from running PyScaffold."""

    success: bool
    error: str = ""


@dataclass
class E2EVerificationResult:
    """Result from E2E test verification."""

    success: bool
    error: str = ""


@dataclass
class TestInventoryResult:
    """Result from collecting tests."""

    tests: Set[str]
    collection_error: str = ""


# Task-wrapped versions of operations for UI visibility
@task(persist_result=True, name="run-scaffold")
async def run_scaffold_task(cmd: list[str]) -> ScaffoldResult:
    """Run PyScaffold putup command (as Prefect task for UI visibility)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return ScaffoldResult(success=True)
        else:
            return ScaffoldResult(
                success=False, error=result.stderr or result.stdout
            )
    except Exception as e:
        return ScaffoldResult(success=False, error=str(e))


@task(persist_result=True, name="run-e2e-verification")
async def run_e2e_verification_task(e2e_dir: Path) -> E2EVerificationResult:
    """Run E2E test verification with mock program (as Prefect task for UI visibility)."""
    try:
        result = subprocess.run(
            ["python", "run_tests.py", str(e2e_dir / "mock_program.py")],
            cwd=str(e2e_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return E2EVerificationResult(success=True)
        else:
            return E2EVerificationResult(
                success=False,
                error=f"Tests failed:\n{result.stdout}\n{result.stderr}",
            )
    except Exception as e:
        return E2EVerificationResult(success=False, error=str(e))


@task(persist_result=True, name="run-prototype-e2e-test")
async def run_prototype_e2e_test_task(
    proto_dir: Path, package_name: str
) -> E2EVerificationResult:
    """Run E2E tests against the prototype (as Prefect task for UI visibility)."""
    proto_dir = Path(proto_dir)
    e2e_dir = proto_dir.parent / "e2e-tests"
    venv_dir = proto_dir / ".venv"

    try:
        # Create virtualenv if it doesn't exist
        if not venv_dir.exists():
            result = subprocess.run(
                ["python", "-m", "venv", str(venv_dir)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return E2EVerificationResult(
                    success=False,
                    error=f"Failed to create venv:\n{result.stdout}\n{result.stderr}",
                )

        # Install the prototype in editable mode
        pip_path = venv_dir / "bin" / "pip"
        result = subprocess.run(
            [str(pip_path), "install", "-e", "."],
            cwd=str(proto_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return E2EVerificationResult(
                success=False,
                error=f"Failed to install prototype:\n{result.stdout}\n{result.stderr}",
            )

        # Run E2E tests using the CLI entrypoint from the venv
        cli_path = venv_dir / "bin" / package_name
        result = subprocess.run(
            ["python", "run_tests.py", str(cli_path)],
            cwd=str(e2e_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return E2EVerificationResult(success=True)
        else:
            return E2EVerificationResult(
                success=False,
                error=f"{result.stdout}\n{result.stderr}",
            )
    except Exception as e:
        return E2EVerificationResult(success=False, error=str(e))


@task(persist_result=True, name="get-test-inventory")
def get_test_inventory_task(tests_dir: Path) -> TestInventoryResult:
    """Get set of test node IDs in tests directory (as Prefect task for UI visibility)."""
    logger = get_run_logger()
    production_dir = tests_dir.parent
    pytest_path = production_dir / ".venv" / "bin" / "pytest"

    cmd = [
        str(pytest_path),
        "--collect-only",
        "-q",
        "-p",
        "no:cov",
        "-o",
        "addopts=",
        str(tests_dir),
    ]
    logger.info(f"[TEST-INVENTORY] Running: {' '.join(cmd)}")
    logger.info(f"[TEST-INVENTORY] cwd: {production_dir}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(production_dir)
        )
        logger.info(f"[TEST-INVENTORY] Return code: {result.returncode}")

        tests = set()
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line and "::" in line and not line.startswith(("=", "-", "no tests")):
                tests.add(line)

        collection_error = ""
        if result.returncode != 0 and "ERROR collecting" in result.stdout:
            collection_error = result.stdout

        logger.info(f"[TEST-INVENTORY] Found {len(tests)} tests")
        return TestInventoryResult(tests=tests, collection_error=collection_error)
    except Exception as e:
        logger.error(f"[TEST-INVENTORY] Error: {e}")
        return TestInventoryResult(tests=set(), collection_error=str(e))


class BreakFixConfig(Block):
    """Configuration block for BreakFix pipeline."""

    _block_type_name = "breakfix-config"
    _block_type_slug = "breakfix-config"

    analyst_model: str = Field(
        default="openai:gpt-5-mini",
        description="Model to use for the Analyst agent",
    )
    prototyper_max_iterations: int = Field(
        default=5,
        description="Maximum iterations for prototyper feedback loop",
    )
    ratchet_max_retries: int = Field(
        default=3,
        description="Maximum retries for ratchet red/green phases",
    )

    def create_analyst(self):
        """Create an Analyst agent with the configured model.

        The returned agent uses pause_flow_run internally in its ask_user tool.
        Wrap with PrefectAgent before running to ensure tool calls execute
        as Prefect tasks with proper flow context.
        """
        from breakfix.agents import create_analyst

        return create_analyst(model=self.analyst_model)

    async def run_scaffold(self, cmd: list[str]) -> ScaffoldResult:
        """Run PyScaffold putup command (delegates to task for UI visibility)."""
        return await run_scaffold_task(cmd)

    async def run_e2e_verification(self, e2e_dir: Path) -> E2EVerificationResult:
        """Run E2E test verification (delegates to task for UI visibility)."""
        return await run_e2e_verification_task(e2e_dir)

    async def run_prototype_e2e_test(
        self, proto_dir: Path, package_name: str
    ) -> E2EVerificationResult:
        """Run E2E tests against the prototype (delegates to task for UI visibility)."""
        return await run_prototype_e2e_test_task(proto_dir, package_name)

    def get_test_inventory_with_errors(self, tests_dir: Path) -> TestInventoryResult:
        """Get set of test node IDs (delegates to task for UI visibility)."""
        return get_test_inventory_task(tests_dir)


async def get_config() -> BreakFixConfig:
    """Get or create the default BreakFix configuration.

    Tries to load from Prefect blocks, falls back to default config.
    """
    try:
        return await BreakFixConfig.load("default")
    except ValueError:
        # Block not registered, use default
        return BreakFixConfig()
