"""Workspace copy operations for the ratchet cycle."""
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CopyResult:
    """Result from copying prototype to production."""
    success: bool
    error: str = ""


async def copy_prototype_to_production(working_dir: Path) -> CopyResult:
    """Copy prototype/ to production/ for ratchet cycle.

    Creates a fresh workspace for the ratchet cycle by copying
    the entire prototype directory (including .git/).

    Args:
        working_dir: The project working directory containing prototype/

    Returns:
        CopyResult indicating success or failure
    """
    proto_dir = working_dir / "prototype"
    prod_dir = working_dir / "production"

    try:
        if prod_dir.exists():
            shutil.rmtree(prod_dir)
        shutil.copytree(proto_dir, prod_dir)
        return CopyResult(success=True)
    except Exception as e:
        return CopyResult(success=False, error=str(e))
