"""Coverage intersection checking for Ratchet Green phase."""
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CoverageCheckResult:
    """Result of coverage intersection check."""
    success: bool
    dead_code_lines: set[int] = field(default_factory=set)
    error: str = ""


def run_pytest_with_coverage(
    production_dir: Path,
    source_file: str,
) -> tuple[bool, dict | None, str]:
    """
    Run pytest with coverage targeting a specific source file.

    Args:
        production_dir: Path to production/ directory
        source_file: Path to source file (can be absolute or relative)

    Returns:
        Tuple of (tests_passed, coverage_data, output)
    """
    pytest_path = production_dir / ".venv" / "bin" / "pytest"
    tests_dir = production_dir / "tests"
    coverage_json_path = production_dir / "coverage.json"

    # Remove old coverage file
    if coverage_json_path.exists():
        coverage_json_path.unlink()

    # --cov needs the source directory, not a specific file
    # Convert the file path to its parent src directory
    source_path = Path(source_file)
    if source_path.is_absolute():
        # Make it relative to production_dir
        try:
            source_path = source_path.relative_to(production_dir)
        except ValueError:
            # If not relative to production_dir, use as-is
            pass

    # Get the src directory (e.g., "src/thedump" from "src/thedump/idea_capture/core.py")
    # We want to cover the whole src tree to catch all imports
    src_dir = production_dir / "src"

    cmd = [
        str(pytest_path),
        "-v",
        f"--cov={src_dir}",
        "--cov-report=json",  # Will output to coverage.json in cwd
        str(tests_dir),
    ]

    print(f"[COVERAGE] Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(production_dir),
            timeout=180,
        )

        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr

        print(f"[COVERAGE] Pytest return code: {result.returncode}")
        print(f"[COVERAGE] Looking for coverage file at: {coverage_json_path}")

        coverage_data = None
        if coverage_json_path.exists():
            with open(coverage_json_path) as f:
                coverage_data = json.load(f)
            print(f"[COVERAGE] Coverage data loaded from {coverage_json_path}")
        else:
            # Check if it was created elsewhere
            print(f"[COVERAGE] WARNING: Coverage file not found at {coverage_json_path}")
            # List files in production_dir to debug
            files = list(production_dir.glob("*.json")) + list(production_dir.glob(".coverage*"))
            print(f"[COVERAGE] WARNING: JSON/coverage files in {production_dir}: {files}")

        return (result.returncode == 0), coverage_data, output

    except subprocess.TimeoutExpired:
        return False, None, "Coverage run timed out after 180 seconds"
    except Exception as e:
        print(f"[COVERAGE] ERROR: {e}")
        return False, None, f"Coverage run failed: {e}"


def check_coverage_intersection(
    coverage_data: dict,
    module_path: str,
    start_line: int,
    end_line: int,
) -> set[int]:
    """
    Check for dead code in the function range.

    Args:
        coverage_data: Parsed coverage JSON data
        module_path: Relative path to module (e.g., "src/pkg/core.py")
        start_line: Function start line
        end_line: Function end line

    Returns:
        Set of line numbers that are dead code (missing coverage within function range)
    """
    files_data = coverage_data.get("files", {})

    # Find the file - may be stored with different path formats
    file_data = None
    for key in files_data:
        # Match by suffix (handles absolute vs relative paths)
        if key.endswith(module_path) or module_path.endswith(key) or key == module_path:
            file_data = files_data[key]
            break

    if file_data is None:
        print(f"[COVERAGE] WARNING: File {module_path} not found in coverage data")
        print(f"[COVERAGE] WARNING: Available files: {list(files_data.keys())}")
        return set()

    missing_lines = set(file_data.get("missing_lines", []))
    function_range = set(range(start_line, end_line + 1))

    # Dead code = missing lines within the function's range
    dead_code = missing_lines & function_range

    if dead_code:
        print(f"[COVERAGE] Dead code detected in {module_path}:{start_line}-{end_line}: {dead_code}")
    else:
        print(f"[COVERAGE] No dead code in {module_path}:{start_line}-{end_line}")

    return dead_code


def get_baseline_path(working_dir: Path, unit_fqn: str) -> Path:
    """Get path to coverage baseline file for a unit."""
    # Sanitize FQN for filesystem: replace dots and slashes
    safe_name = unit_fqn.replace(".", "_").replace("/", "_")
    return working_dir / ".breakfix" / "coverage" / f"{safe_name}.json"


def load_baseline(working_dir: Path, unit_fqn: str) -> set[int] | None:
    """Load coverage baseline for a unit.

    Args:
        working_dir: Project working directory
        unit_fqn: Fully qualified name of the unit

    Returns:
        Set of executed lines from previous cycle, or None if no baseline exists
    """
    path = get_baseline_path(working_dir, unit_fqn)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return set(data.get("executed_lines", []))
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[COVERAGE] WARNING: Failed to load baseline: {e}")
        return None


def save_baseline(
    working_dir: Path,
    unit_fqn: str,
    coverage_data: dict,
    module_path: str,
    start_line: int,
    end_line: int,
) -> None:
    """Save coverage baseline for a unit after successful green phase.

    Args:
        working_dir: Project working directory
        unit_fqn: Fully qualified name of the unit
        coverage_data: Parsed coverage JSON data
        module_path: Relative path to module
        start_line: Function start line
        end_line: Function end line
    """
    files_data = coverage_data.get("files", {})

    # Find the file data
    file_data = None
    for key in files_data:
        if key.endswith(module_path) or module_path.endswith(key) or key == module_path:
            file_data = files_data[key]
            break

    if file_data is None:
        print(f"[COVERAGE] WARNING: Cannot save baseline: {module_path} not found")
        return

    executed_lines = set(file_data.get("executed_lines", []))
    function_range = set(range(start_line, end_line + 1))
    executed_in_function = executed_lines & function_range

    path = get_baseline_path(working_dir, unit_fqn)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        json.dump({"executed_lines": sorted(executed_in_function)}, f, indent=2)

    print(f"[COVERAGE] Saved baseline: {len(executed_in_function)} lines to {path}")


def format_coverage_feedback(
    dead_code_lines: set[int],
    module_path: str,
    production_dir: Path,
) -> str:
    """Format feedback message for coverage violation.

    Args:
        dead_code_lines: Set of line numbers with dead code
        module_path: Relative path to module
        production_dir: Path to production/ directory

    Returns:
        Formatted feedback message for the agent
    """
    lines_str = ", ".join(str(ln) for ln in sorted(dead_code_lines))

    # Read source file to show actual code
    source_path = production_dir / module_path
    snippets = []
    if source_path.exists():
        source_lines = source_path.read_text().split("\n")
        for ln in sorted(dead_code_lines):
            if 0 < ln <= len(source_lines):
                snippets.append(f"  Line {ln}: {source_lines[ln-1].rstrip()}")

    snippet_text = "\n".join(snippets) if snippets else "(Could not read source)"

    return f"""Coverage check failed: You added code that is not executed by tests (dead code).

## Dead Code Detected
Lines: {lines_str}

{snippet_text}

## Instructions
1. Review the lines above - they are never executed during tests
2. Either:
   a. Remove the dead code if it's unnecessary, OR
   b. The test does not exercise this code path - simplify your implementation
3. Remember: Only write the MINIMAL code needed to pass the test

You can ONLY edit {module_path}

CRITICAL: DO NOT RUN THE TESTS. I, THE USER, WILL RUN THEM FOR YOU AND PASTE THE OUTPUT.
"""
