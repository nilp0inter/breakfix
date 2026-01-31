"""Inter-module dependency graph using pydeps."""
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


@dataclass
class ModuleInfo:
    """Information about a module from pydeps."""
    name: str
    path: Optional[str]
    imports: List[str] = field(default_factory=list)
    imported_by: List[str] = field(default_factory=list)


def get_module_graph(src_dir: Path, package_name: str) -> Dict[str, ModuleInfo]:
    """
    Run pydeps and parse JSON output.

    Args:
        src_dir: Path to the src/ directory containing the package
        package_name: Name of the package to analyze

    Returns:
        Dictionary mapping module FQN to ModuleInfo
    """
    package_path = src_dir / package_name

    cmd = [
        "pydeps",
        str(package_path),
        "--show-deps",
        "--nodot",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    raw_graph = json.loads(result.stdout)

    modules: Dict[str, ModuleInfo] = {}
    for name, info in raw_graph.items():
        # Skip __main__ and modules without paths (external or virtual)
        if name == "__main__":
            continue

        # Only include modules that are part of our package
        if not name.startswith(package_name):
            continue

        modules[name] = ModuleInfo(
            name=name,
            path=info.get("path"),
            imports=[
                imp for imp in info.get("imports", [])
                if imp.startswith(package_name) and imp != "__main__"
            ],
            imported_by=[
                imp for imp in info.get("imported_by", [])
                if imp.startswith(package_name) and imp != "__main__"
            ],
        )

    return modules


def topological_sort_modules(modules: Dict[str, ModuleInfo]) -> List[str]:
    """
    Topologically sort modules, emitting leaf nodes first.

    Leaf nodes are modules that have no imports (or only import external modules).
    Then we emit modules whose imports have all been emitted.

    This uses Kahn's algorithm.

    Args:
        modules: Dictionary of module FQN to ModuleInfo

    Returns:
        List of module FQNs in topological order (leaves first)
    """
    if not modules:
        return []

    # Build in-degree count (number of internal imports)
    in_degree: Dict[str, int] = defaultdict(int)
    dependents: Dict[str, List[str]] = defaultdict(list)

    for name, info in modules.items():
        # Initialize in_degree for all modules
        if name not in in_degree:
            in_degree[name] = 0

        # Count only internal imports (within our package)
        for imp in info.imports:
            if imp in modules:
                in_degree[name] += 1
                dependents[imp].append(name)

    # Start with modules that have no internal imports (leaf nodes)
    queue: List[str] = [name for name, degree in in_degree.items() if degree == 0]
    result: List[str] = []

    while queue:
        # Process in alphabetical order for determinism
        queue.sort()
        current = queue.pop(0)
        result.append(current)

        # Reduce in-degree for modules that import this one
        for dependent in dependents[current]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    # Check for cycles (modules not in result)
    if len(result) != len(modules):
        # There's a cycle - include remaining modules at the end
        remaining = [name for name in modules if name not in result]
        result.extend(sorted(remaining))

    return result


def get_sorted_modules(src_dir: Path, package_name: str) -> List[ModuleInfo]:
    """
    Get modules in topological order (leaves first).

    Args:
        src_dir: Path to the src/ directory
        package_name: Name of the package

    Returns:
        List of ModuleInfo in topological order
    """
    modules = get_module_graph(src_dir, package_name)
    sorted_names = topological_sort_modules(modules)
    return [modules[name] for name in sorted_names if modules[name].path]
