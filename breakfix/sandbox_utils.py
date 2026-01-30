from pydantic_ai_filesystem_sandbox import (
    FileSystemToolset,
    Sandbox,
    SandboxConfig,
    Mount,
)
from breakfix.models import BreakfixConfig
from pathlib import Path
from typing import List, Set, Dict, Any, Tuple
import os
import random


def _resolve_dirs(root: Path, dir_names: List[str]) -> Set[Path]:
    """
    Resolves a list of directory names relative to the root path.
    Returns a set of absolute Paths that exist and are directories.
    """
    resolved_dirs = set()
    for name in dir_names:
        candidate = root / name
        if candidate.is_dir():
            resolved_dirs.add(candidate)
    return resolved_dirs


def get_mounted_paths(config: BreakfixConfig) -> Tuple[List[str], List[str]]:
    """
    Returns lists of mounted code and test paths within the sandbox.
    """
    root = config.project_root.resolve()

    code_host_dirs = _resolve_dirs(root, config.code_dirs)
    test_host_dirs = _resolve_dirs(root, config.test_dirs)

    code_mounted_paths = [f"/project/{d.name}" for d in code_host_dirs]
    test_mounted_paths = [f"/project/{d.name}" for d in test_host_dirs]
    
    return code_mounted_paths, test_mounted_paths


def _create_mounts(config: BreakfixConfig, access_map: dict) -> List[Mount]:
    """
    Creates a list of mounts based on the configuration and access map.
    access_map: dict mapping 'code', 'tests' to 'ro' or 'rw'.
    """
    mounts = []
    root = config.project_root.resolve()

    # Identify directories for each category
    code_dirs = _resolve_dirs(root, config.code_dirs)
    test_dirs = _resolve_dirs(root, config.test_dirs)
    
    # Helper to add mounts
    def add_mounts(directories, mode):
        for d in directories:
            # Mount at the same relative path in the sandbox, e.g., /project/breakfix
            mount_point = f"/project/{d.name}"
            mounts.append(Mount(host_path=d, mount_point=mount_point, mode=mode)) # type: ignore

    if 'code' in access_map:
        add_mounts(code_dirs, access_map['code'])
    
    if 'tests' in access_map:
        add_mounts(test_dirs, access_map['tests'])
    
    return mounts

def get_architect_toolset(config: BreakfixConfig) -> FileSystemToolset:
    # Architect: RO on everything
    mounts = _create_mounts(config, {'code': 'ro', 'tests': 'ro'})
    sandbox = Sandbox(SandboxConfig(mounts=mounts))
    return FileSystemToolset(sandbox)

def get_pioneer_toolset(config: BreakfixConfig) -> FileSystemToolset:
    # Pioneer: RW on Tests, RO on Code
    mounts = _create_mounts(config, {'code': 'ro', 'tests': 'rw'})
    sandbox = Sandbox(SandboxConfig(mounts=mounts))
    return FileSystemToolset(sandbox)

def get_gatekeeper_toolset(config: BreakfixConfig) -> FileSystemToolset:
    # Gatekeeper: RO on everything
    mounts = _create_mounts(config, {'code': 'ro', 'tests': 'ro'})
    sandbox = Sandbox(SandboxConfig(mounts=mounts))
    return FileSystemToolset(sandbox)

def get_builder_toolset(config: BreakfixConfig) -> FileSystemToolset:
    # Builder: RW on Code, RO on Tests
    mounts = _create_mounts(config, {'code': 'rw', 'tests': 'ro'})
    sandbox = Sandbox(SandboxConfig(mounts=mounts))
    return FileSystemToolset(sandbox)

def get_pruner_toolset(config: BreakfixConfig) -> FileSystemToolset:
    # Pruner: RW on Code, RO on Tests
    mounts = _create_mounts(config, {'code': 'rw', 'tests': 'ro'})
    sandbox = Sandbox(SandboxConfig(mounts=mounts))
    return FileSystemToolset(sandbox)

def get_sniper_toolset(config: BreakfixConfig) -> FileSystemToolset:
    # Sniper: RW on Code (for mutation), RO on Tests
    mounts = _create_mounts(config, {'code': 'rw', 'tests': 'ro'})
    sandbox = Sandbox(SandboxConfig(mounts=mounts))
    return FileSystemToolset(sandbox)

def get_curator_toolset(config: BreakfixConfig) -> FileSystemToolset:
    # Curator: RW on Code and Tests (refactoring)
    mounts = _create_mounts(config, {'code': 'rw', 'tests': 'rw'})
    sandbox = Sandbox(SandboxConfig(mounts=mounts))
    return FileSystemToolset(sandbox)


# Fake Tool Functions

def run_coverage_analysis(file_paths: List[str]) -> Dict[str, Any]:
    """
    Simulates running a code coverage analysis tool on the provided files.
    Returns a dictionary containing coverage statistics and recommendations.
    """
    # Generate a dummy coverage report
    report = {
        "coverage_percentage": 95.0,
        "unused_lines": [],
        "dead_functions": [],
        "recommendations": ["Code coverage is high. No immediate actions needed."]
    }
    
    # Randomly add some "issues" to make it look realistic
    if random.choice([True, False]):
        report["unused_lines"] = ["def unused_helper():", "    pass"]
        report["dead_functions"] = ["unused_helper"]
        report["recommendations"].append("Consider removing 'unused_helper'.")
        report["coverage_percentage"] = 85.5
        
    return report


def run_mutation_testing(file_paths: List[str]) -> Dict[str, Any]:
    """
    Simulates running a mutation testing tool on the provided files.
    Returns a dictionary containing mutation scores and survivors.
    This tool modifies the code in memory/sandbox to run tests, but cleans up after itself.
    """
    # Generate a dummy mutation report
    report = {
        "weakness_score": 10.0,
        "mutations_survived": [],
        "tests_to_add": []
    }
    
    # Randomly add some survivors
    if random.choice([True, False]):
        report["weakness_score"] = 45.0
        report["mutations_survived"] = [
            "Mutated '+' to '-' in function",
            "Removed return statement"
        ]
        report["tests_to_add"] = [
            "Test addition with negative numbers",
            "Verify return value is not None"
        ]
        
    return report