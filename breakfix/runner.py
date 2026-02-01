import logging
import random
import subprocess
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path

from typing import Set

from breakfix.agents import (
    create_analyst,
    run_e2e_builder,
    analyze_interface,
    run_prototyper,
    review_architecture,
    run_refactorer,
    run_oracle,
    run_ratchet_red,
    run_ratchet_green,
)
from breakfix.distiller import run_distiller
from breakfix.graph import run_graph, NodeErrored, NodeFailed
from breakfix.workspace import copy_prototype_to_production, cleanup_production_code
from breakfix.nodes import (
    TestCase,
    UnitWorkItem,
    start_project_node,
)


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


def get_test_inventory(tests_dir: Path) -> Set[str]:
    """Get set of test node IDs in tests directory using pytest --collect-only."""
    production_dir = tests_dir.parent
    pytest_path = production_dir / ".venv" / "bin" / "pytest"

    # Use -p no:cov to disable coverage plugin (setup.cfg may have --cov flags)
    # Use -o addopts= to clear any addopts from setup.cfg/pyproject.toml
    cmd = [
        str(pytest_path),
        "--collect-only", "-q",
        "-p", "no:cov",
        "-o", "addopts=",
        str(tests_dir)
    ]
    logging.info(f"[TEST-INVENTORY] Running: {' '.join(cmd)}")
    logging.info(f"[TEST-INVENTORY] cwd: {production_dir}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(production_dir)
        )
        logging.info(f"[TEST-INVENTORY] Return code: {result.returncode}")
        logging.info(f"[TEST-INVENTORY] stdout: {result.stdout[:500] if result.stdout else '(empty)'}")
        logging.info(f"[TEST-INVENTORY] stderr: {result.stderr[:500] if result.stderr else '(empty)'}")

        # Parse output: each line is a test node ID like "tests/test_core.py::test_func"
        tests = set()
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if line and '::' in line and not line.startswith(('=', '-', 'no tests')):
                tests.add(line)

        logging.info(f"[TEST-INVENTORY] Found {len(tests)} tests: {tests}")
        return tests
    except Exception as e:
        logging.error(f"[TEST-INVENTORY] Error: {e}")
        return set()


async def run(working_directory: str):
    def sim_check(prob):
        # Helper for mock probabilities
        return random.random() < prob

    async def run_scaffold(cmd):
        """Run PyScaffold putup command."""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return ScaffoldResult(success=True)
            else:
                return ScaffoldResult(success=False, error=result.stderr or result.stdout)
        except Exception as e:
            return ScaffoldResult(success=False, error=str(e))

    async def run_e2e_verification(e2e_dir: Path):
        """Run E2E test verification with mock program."""
        try:
            result = subprocess.run(
                ["python", "run_tests.py", str(e2e_dir / "mock_program.py")],
                cwd=str(e2e_dir),
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return E2EVerificationResult(success=True)
            else:
                return E2EVerificationResult(
                    success=False,
                    error=f"Tests failed:\n{result.stdout}\n{result.stderr}"
                )
        except Exception as e:
            return E2EVerificationResult(success=False, error=str(e))

    async def run_prototype_e2e_test(proto_dir: Path, package_name: str):
        """Run E2E tests against the prototype.

        Creates a virtualenv, installs the prototype package, and runs
        the E2E tests using the CLI entrypoint.
        """
        proto_dir = Path(proto_dir)
        e2e_dir = proto_dir.parent / "e2e-tests"
        venv_dir = proto_dir / ".venv"

        try:
            # Create virtualenv if it doesn't exist
            if not venv_dir.exists():
                result = subprocess.run(
                    ["python", "-m", "venv", str(venv_dir)],
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    return E2EVerificationResult(
                        success=False,
                        error=f"Failed to create venv:\n{result.stdout}\n{result.stderr}"
                    )

            # Install the prototype in editable mode
            pip_path = venv_dir / "bin" / "pip"
            result = subprocess.run(
                [str(pip_path), "install", "-e", "."],
                cwd=str(proto_dir),
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return E2EVerificationResult(
                    success=False,
                    error=f"Failed to install prototype:\n{result.stdout}\n{result.stderr}"
                )

            # Run E2E tests using the CLI entrypoint from the venv
            cli_path = venv_dir / "bin" / package_name
            result = subprocess.run(
                ["python", "run_tests.py", str(cli_path)],
                cwd=str(e2e_dir),
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return E2EVerificationResult(success=True)
            else:
                return E2EVerificationResult(
                    success=False,
                    error=f"{result.stdout}\n{result.stderr}"
                )
        except Exception as e:
            return E2EVerificationResult(success=False, error=str(e))

    deps = Namespace(
        input=input,  # Used elsewhere
        working_directory=working_directory,  # For inner graph access

        # Analyst agent factory (input_fn baked in)
        create_analyst=lambda: create_analyst(model="openai:gpt-5-mini", input_fn=input),

        # Phase 1a: E2E Test Builder
        run_e2e_builder=run_e2e_builder,
        run_e2e_verification=run_e2e_verification,
        analyze_interface=analyze_interface,

        # Phase 1b: Scaffolding
        run_scaffold=run_scaffold,

        # Phase 2: Prototyping
        run_prototyper=run_prototyper,
        run_prototype_e2e_test=run_prototype_e2e_test,

        # Phase 3: Refinement
        run_refactorer=run_refactorer,
        review_architecture=review_architecture,

        # Phase 4: Distillation
        run_distiller=run_distiller,
        copy_prototype_to_production=copy_prototype_to_production,
        cleanup_production_code=cleanup_production_code,

        # Phase 5: Oracle
        run_oracle=run_oracle,

        # Phase 6: Ratchet - Red Phase (Tester Agent)
        run_ratchet_red=run_ratchet_red,
        get_test_inventory=get_test_inventory,

        # Phase 6: Ratchet - Green Phase (Developer Agent)
        run_ratchet_green=run_ratchet_green,

        # Phase 7: Crucible Agents & Checks
        process_mutation_testing=lambda u: 1.0 if sim_check(0.6) else 0.5,
        agent_sentinel=lambda u: "test_killer()",
        check_mutant_killed=lambda t: sim_check(0.8),
        agent_optimizer=lambda u, c: "optimized_code()",
        check_regression=lambda c: not sim_check(0.8)
    )

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    # Create checkpoint directory
    checkpoint_dir = Path(working_directory) / ".breakfix" / "execution"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Start the Outer Graph with working directory
        result = await run_graph(
            start_project_node,
            working_directory,
            deps=deps,
            checkpoint_dir=checkpoint_dir
        )
        print(f"\nFinal Artifact: {result}")

    except (NodeErrored, NodeFailed) as e:
        print(f"System Halted: {e}")
