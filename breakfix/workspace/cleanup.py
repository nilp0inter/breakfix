"""Production code cleanup for TDD - stub functions with NotImplementedError."""
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from breakfix.nodes import UnitWorkItem


@dataclass
class CleanupResult:
    """Result from cleaning up production code."""
    success: bool
    files_modified: int = 0
    functions_stubbed: int = 0
    error: str = ""


def stub_function_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    """Replace function body with raise NotImplementedError, preserving docstring."""
    new_body = []

    # Preserve docstring if present (first statement is a string literal)
    if (node.body and
        isinstance(node.body[0], ast.Expr) and
        isinstance(node.body[0].value, ast.Constant) and
        isinstance(node.body[0].value.value, str)):
        new_body.append(node.body[0])

    # Add raise NotImplementedError
    new_body.append(ast.Raise(
        exc=ast.Call(
            func=ast.Name(id='NotImplementedError', ctx=ast.Load()),
            args=[],
            keywords=[]
        ),
        cause=None
    ))

    node.body = new_body


def process_file(file_path: Path) -> int:
    """Process a single file, stub all functions/methods, return count."""
    source = file_path.read_text()
    tree = ast.parse(source)
    count = 0

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stub_function_body(node)
            count += 1

    # Fix missing line numbers for AST nodes (required by unparse)
    ast.fix_missing_locations(tree)

    new_source = ast.unparse(tree)
    file_path.write_text(new_source)

    return count


def get_target_files(unit_queue: List["UnitWorkItem"]) -> Set[Path]:
    """
    Get set of file paths that need cleanup.

    Filters unit_queue for shell.py and core.py files.
    """
    target_files: Set[Path] = set()

    for unit in unit_queue:
        if not unit.module_path:
            continue

        # Check if it's a shell.py or core.py file
        if not (unit.module_path.endswith("shell.py") or
                unit.module_path.endswith("core.py")):
            continue

        target_files.add(Path(unit.module_path))

    return target_files


async def cleanup_production_code(
    unit_queue: List["UnitWorkItem"],
) -> CleanupResult:
    """
    Find shell.py and core.py files from unit_queue and stub their functions.

    Args:
        unit_queue: List of UnitWorkItem from distillation (with production paths)

    Returns:
        CleanupResult with counts of files/functions modified
    """
    try:
        target_files = get_target_files(unit_queue)

        files_modified = 0
        functions_stubbed = 0

        for file_path in sorted(target_files):
            if not file_path.exists():
                continue
            count = process_file(file_path)
            if count > 0:
                files_modified += 1
                functions_stubbed += count

        return CleanupResult(
            success=True,
            files_modified=files_modified,
            functions_stubbed=functions_stubbed
        )
    except Exception as e:
        return CleanupResult(success=False, error=str(e))
