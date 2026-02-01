"""Workspace copy operations for the ratchet cycle."""
import configparser
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CopyResult:
    """Result from copying prototype to production."""
    success: bool
    error: str = ""


def _clean_setup_cfg(setup_cfg_path: Path) -> None:
    """Remove [tool:pytest] section from setup.cfg for clean test collection.

    The prototype may have pytest configuration with coverage plugins that
    interfere with test collection when code has NotImplementedError stubs.
    """
    if not setup_cfg_path.exists():
        return

    config = configparser.ConfigParser()
    config.read(setup_cfg_path)

    # Remove the [tool:pytest] section if it exists
    if config.has_section("tool:pytest"):
        config.remove_section("tool:pytest")

        with open(setup_cfg_path, "w") as f:
            config.write(f)


async def copy_prototype_to_production(working_dir: Path) -> CopyResult:
    """Copy prototype/ to production/ for ratchet cycle.

    Creates a fresh workspace for the ratchet cycle by:
    1. Copying the entire prototype directory
    2. Clearing the tests/ folder (for TDD from scratch)
    3. Removing [tool:pytest] section from setup.cfg (clean slate)
    4. Recreating the virtualenv
    5. Installing the project with testing dependencies

    Args:
        working_dir: The project working directory containing prototype/

    Returns:
        CopyResult indicating success or failure
    """
    proto_dir = working_dir / "prototype"
    prod_dir = working_dir / "production"

    try:
        # Step 1: Copy prototype to production
        if prod_dir.exists():
            shutil.rmtree(prod_dir)
        shutil.copytree(proto_dir, prod_dir)

        # Step 2: Clear tests/ folder contents (keep the directory)
        tests_dir = prod_dir / "tests"
        if tests_dir.exists():
            shutil.rmtree(tests_dir)
        tests_dir.mkdir(exist_ok=True)

        # Step 3: Remove [tool:pytest] section from setup.cfg
        setup_cfg = prod_dir / "setup.cfg"
        _clean_setup_cfg(setup_cfg)

        # Step 4: Remove old .venv and create a fresh virtualenv
        venv_dir = prod_dir / ".venv"
        if venv_dir.exists():
            shutil.rmtree(venv_dir)

        result = subprocess.run(
            ["python", "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            cwd=str(prod_dir),
        )
        if result.returncode != 0:
            return CopyResult(
                success=False,
                error=f"Failed to create virtualenv: {result.stderr}"
            )

        # Step 5: Install project with testing dependencies + pytest-cov for coverage
        pip_path = venv_dir / "bin" / "pip"
        result = subprocess.run(
            [str(pip_path), "install", "-e", ".[testing]", "pytest-cov"],
            capture_output=True,
            text=True,
            cwd=str(prod_dir),
        )
        if result.returncode != 0:
            return CopyResult(
                success=False,
                error=f"Failed to install project: {result.stderr}"
            )

        return CopyResult(success=True)
    except Exception as e:
        return CopyResult(success=False, error=str(e))
