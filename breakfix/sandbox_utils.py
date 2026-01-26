from pydantic_ai_filesystem_sandbox import FileSystemToolset, Sandbox, SandboxConfig, Mount
from breakfix.models import BreakfixConfig
from pathlib import Path
from typing import List

def get_architect_toolset(config: BreakfixConfig) -> FileSystemToolset:
    """
    Creates a FileSystemToolset for the Architect agent.
    The Architect needs read-only access to relevant parts of the project for context.
    """
    project_root = config.project_root.resolve()

    mounts = [
        # Mount the 'breakfix' source directory
        Mount(host_path=str(project_root / "breakfix"), mount_point="/app", mode="ro"),
        # Mount the 'tests' directory (if it exists)
        Mount(host_path=str(project_root / "tests"), mount_point="/tests", mode="ro"),
        # Mount specific important files from the project root
        Mount(host_path=str(project_root / "pyproject.toml"), mount_point="/pyproject.toml", mode="ro"),
        Mount(host_path=str(project_root / "README.md"), mount_point="/README.md", mode="ro"),
        Mount(host_path=str(project_root / "GEMINI.md"), mount_point="/GEMINI.md", mode="ro"),
        Mount(host_path=str(project_root / "pydantic-ai.docs.txt"), mount_point="/pydantic-ai.docs.txt", mode="ro"),
    ]

    # Filter out mounts where the host_path does not exist
    existing_mounts = [m for m in mounts if Path(m.host_path).exists()]

    sandbox_config = SandboxConfig(mounts=existing_mounts)
    sandbox = Sandbox(sandbox_config)
    return FileSystemToolset(sandbox)

# You can add similar functions for other agents later:
# def get_pioneer_toolset(config: BreakfixConfig) -> FileSystemToolset:
#     ...