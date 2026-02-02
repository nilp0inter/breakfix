"""Scaffold task - Initialize project structure using PyScaffold."""

from pathlib import Path

from prefect import task
from prefect.logging import get_run_logger

from breakfix.artifacts import scaffold_artifacts
from breakfix.blocks import BreakFixConfig, get_config
from breakfix.state import ProjectState


class ScaffoldError(Exception):
    """Scaffolding failed."""

    pass


def _patch_setup_cfg_entrypoint(setup_cfg_path: Path, package_name: str):
    """Add console_scripts entry point to setup.cfg."""
    content = setup_cfg_path.read_text()

    entry_points_section = "[options.entry_points]"
    if entry_points_section in content:
        new_section = f"""{entry_points_section}
console_scripts =
    {package_name} = {package_name}.skeleton:run
"""
        start_idx = content.index(entry_points_section)
        rest = content[start_idx + len(entry_points_section) :]
        next_section_idx = rest.find("\n[")
        if next_section_idx == -1:
            content = content[:start_idx] + new_section
        else:
            content = content[:start_idx] + new_section + rest[next_section_idx + 1 :]

        setup_cfg_path.write_text(content)


@task(persist_result=True, name="scaffold")
async def scaffold_task(
    state: ProjectState,
    config: BreakFixConfig | None = None,
) -> ProjectState:
    """Initialize project scaffold using PyScaffold.

    Phase 1b: Creates the prototype/ directory with PyScaffold.
    """
    logger = get_run_logger()
    config = config or await get_config()

    logger.info("[SCAFFOLD] Phase 1b: Project Scaffolding")

    proto_dir = Path(state.working_directory) / "prototype"
    meta = state.project_metadata

    if meta is None:
        raise ScaffoldError("Project metadata is required for scaffolding")

    # Build putup command
    cmd = [
        "putup",
        str(proto_dir),
        "-n",
        meta.project_name,
        "-p",
        meta.package_name,
        "-d",
        meta.description,
        "-l",
        meta.license,
    ]
    if meta.url:
        cmd.extend(["-u", meta.url])
    if meta.github_actions:
        cmd.append("--github-actions")

    logger.info(f"[SCAFFOLD] Running: {' '.join(cmd)}")

    result = await config.run_scaffold(cmd)

    if not result.success:
        raise ScaffoldError(f"Scaffolding failed: {result.error}")

    # Patch setup.cfg to add console_scripts entry point
    setup_cfg_path = proto_dir / "setup.cfg"
    _patch_setup_cfg_entrypoint(setup_cfg_path, meta.package_name)

    logger.info(f"[SCAFFOLD] Project scaffolded at {proto_dir}")

    # Create artifacts for UI visibility
    await scaffold_artifacts(command=cmd, success=True)

    return state
