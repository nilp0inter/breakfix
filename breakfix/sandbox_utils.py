from pydantic_ai_filesystem_sandbox import (
    FileSystemToolset,
    Sandbox,
    SandboxConfig,
    Mount,
)
from breakfix.models import BreakfixConfig
from pathlib import Path
from typing import Any


def get_architect_toolset(config: BreakfixConfig) -> FileSystemToolset:
    """
    Creates a FileSystemToolset for the Architect agent.
    The Architect needs read-only access to relevant parts of the project for context.
    """
    project_root = config.project_root.resolve()

    mounts = [
        # Mount the entire project root as read-only to /project
        Mount(host_path=project_root, mount_point="/project", mode="ro"),  # type: ignore
    ]

    sandbox_config = SandboxConfig(mounts=mounts)
    sandbox = Sandbox(sandbox_config)
    return FileSystemToolset(sandbox)


def get_pioneer_toolset(config: BreakfixConfig) -> FileSystemToolset:
    """
    Creates a FileSystemToolset for the Pioneer agent.
    The Pioneer needs read-only access to understand project structure and test conventions.
    """
    project_root = config.project_root.resolve()

    mounts = [
        # Mount the entire project root as read-only to /project
        Mount(host_path=project_root, mount_point="/project", mode="ro"),  # type: ignore
    ]

    sandbox_config = SandboxConfig(mounts=mounts)
    sandbox = Sandbox(sandbox_config)
    return FileSystemToolset(sandbox)


def get_builder_toolset(config: BreakfixConfig) -> FileSystemToolset:
    """
    Creates a FileSystemToolset for the Builder agent.
    The Builder needs read/write access to code files.
    """
    project_root = config.project_root.resolve()

    mounts = [
        # Mount code directories as read-write
        Mount(host_path=project_root, mount_point="/project", mode="rw"),  # type: ignore
    ]

    sandbox_config = SandboxConfig(mounts=mounts)
    sandbox = Sandbox(sandbox_config)
    return FileSystemToolset(sandbox)


def get_pruner_toolset(config: BreakfixConfig) -> FileSystemToolset:
    """
    Creates a FileSystemToolset for the Pruner agent.
    The Pruner needs read/write access to run coverage reports and remove dead code.
    """
    project_root = config.project_root.resolve()

    mounts = [
        # Mount the entire project root as read-write to /project
        Mount(host_path=project_root, mount_point="/project", mode="rw"),  # type: ignore
    ]

    sandbox_config = SandboxConfig(mounts=mounts)
    sandbox = Sandbox(sandbox_config)
    return FileSystemToolset(sandbox)
