"""Mutation testing runner using Cosmic Ray CLI."""

import ast
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from breakfix.artifacts import agent_input_artifact, agent_output_artifact

# Timeout for cosmic-ray commands (in seconds)
COSMIC_RAY_INIT_TIMEOUT = 120  # 2 minutes for init
COSMIC_RAY_EXEC_TIMEOUT = 600  # 10 minutes for execution
COSMIC_RAY_DUMP_TIMEOUT = 30


@dataclass
class SurvivingMutant:
    """A mutant that survived (wasn't killed by tests)."""
    id: str  # Format: "module:operator:occurrence"
    diff: str  # Unified diff


@dataclass
class MutationResult:
    """Result from running mutation testing."""
    success: bool
    score: float = 0.0  # 0.0 to 1.0 (killed / total)
    surviving_mutants: list[SurvivingMutant] = field(default_factory=list)
    total_mutants: int = 0
    killed_mutants: int = 0
    error: str = ""


def _get_cosmic_ray_path(production_dir: Path) -> Path:
    """Get path to cosmic-ray executable in the virtualenv."""
    return production_dir / ".venv" / "bin" / "cosmic-ray"


def _get_session_paths(production_dir: Path, unit_fqn: str) -> tuple[Path, Path]:
    """Get paths for config and session files for a unit."""
    mutations_dir = production_dir / ".breakfix" / "mutations"
    mutations_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize FQN for filesystem
    safe_name = unit_fqn.replace(".", "_").replace("/", "_")

    config_path = mutations_dir / f"config_{safe_name}.toml"
    session_path = mutations_dir / f"session_{safe_name}.sqlite"

    return config_path, session_path


def _create_cosmic_ray_config(
    production_dir: Path,
    module_path: str,
    config_path: Path,
) -> None:
    """
    Create TOML config file for cosmic-ray targeting specific module.

    Args:
        production_dir: Path to production/ directory
        module_path: Relative path to module (e.g., "src/pkg/module.py")
        config_path: Path to write config file
    """
    # Use relative path from production_dir
    config_content = f'''[cosmic-ray]
module-path = "{module_path}"
timeout = 30.0
test-command = ".venv/bin/pytest tests/"
excluded-modules = []

[cosmic-ray.distributor]
name = "local"
'''

    config_path.write_text(config_content)
    print(f"[MUTATION] Created cosmic-ray config at {config_path}")


def _run_cosmic_ray_command(
    production_dir: Path,
    args: list[str],
    timeout: int,
) -> subprocess.CompletedProcess:
    """Run a cosmic-ray command with proper environment."""
    cosmic_ray_path = _get_cosmic_ray_path(production_dir)

    if not cosmic_ray_path.exists():
        raise FileNotFoundError(
            f"cosmic-ray not found at {cosmic_ray_path}. "
            f"Please install it with: pip install cosmic-ray"
        )

    cmd = [str(cosmic_ray_path)] + args
    print(f"[MUTATION] Running: {' '.join(cmd)}")
    print(f"[MUTATION] cwd: {production_dir}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(production_dir),
        timeout=timeout,
    )

    return result


def _parse_cosmic_ray_dump(
    dump_output: str,
    start_line: int,
    end_line: int,
) -> tuple[list[dict], int, int]:
    """
    Parse JSON output from `cosmic-ray dump` command.

    Cosmic-ray dump outputs one JSON array per line (NDJSON format).
    Each line is: [{job_info}, {result}]
    - job_info contains: job_id, mutations (with module_path, operator_name, occurrence, start_pos)
    - result contains: worker_outcome, test_outcome, diff, output

    Filters mutants to only those within the specified line range.

    Args:
        dump_output: NDJSON string from cosmic-ray dump (one JSON array per line)
        start_line: Start line of function
        end_line: End line of function

    Returns:
        Tuple of (surviving_mutants_data, total_mutants, killed_mutants)
    """
    if not dump_output.strip():
        return [], 0, 0

    # Parse each line as a separate JSON array
    records = []
    for line in dump_output.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            # Each line is a JSON array: [{job_info}, {result}]
            entry = json.loads(line)
            if isinstance(entry, list) and len(entry) >= 2:
                job_info = entry[0]
                result = entry[1]

                # Extract mutation info from job_info
                mutations = job_info.get("mutations", [])
                if mutations:
                    mutation = mutations[0]  # Take first mutation
                    # start_pos is [line, column]
                    start_pos = mutation.get("start_pos", [0, 0])
                    line_num = start_pos[0] if isinstance(start_pos, list) else 0

                    # Build a combined record for our processing
                    record = {
                        "job_id": job_info.get("job_id"),
                        "module_path": mutation.get("module_path", ""),
                        "operator": mutation.get("operator_name", "unknown"),
                        "occurrence": mutation.get("occurrence", 0),
                        "line_number": line_num,
                        "worker_outcome": result.get("worker_outcome", ""),
                        "test_outcome": result.get("test_outcome", ""),
                        "diff": result.get("diff", ""),
                    }
                    records.append(record)
        except json.JSONDecodeError as e:
            print(f"[MUTATION] WARNING: Failed to parse line: {e}")
            continue

    # Filter to mutants within the line range
    filtered_records = []
    for record in records:
        line_num = record.get("line_number", 0)
        if start_line <= line_num <= end_line:
            filtered_records.append(record)

    surviving = []
    killed = 0

    for record in filtered_records:
        test_outcome = record.get("test_outcome", "").lower()
        worker_outcome = record.get("worker_outcome", "").lower()

        # A mutant is killed if tests caught it
        if test_outcome == "killed" or worker_outcome == "timeout":
            killed += 1
        elif test_outcome == "survived" and worker_outcome == "normal":
            surviving.append(record)

    total = len(filtered_records)

    print(
        f"[MUTATION] Parsed {total} mutants in line range [{start_line}, {end_line}]: "
        f"{killed} killed, {len(surviving)} survived"
    )

    return surviving, total, killed


def _make_mutant_id(record: dict) -> str:
    """Create a mutant ID from a cosmic-ray record."""
    # Use module_path if available (from parsed dump), otherwise fall back to module
    module_path = record.get("module_path", record.get("module", "unknown"))
    operator = record.get("operator", "unknown")
    occurrence = record.get("occurrence", 0)
    return f"{module_path}:{operator}:{occurrence}"


def _find_function_line_range(
    module_file: Path,
    function_name: str,
) -> tuple[int, int] | None:
    """
    Find the start and end line numbers of a function in a Python module.

    Args:
        module_file: Path to the Python module file
        function_name: Name of the function to find

    Returns:
        Tuple of (start_line, end_line) or None if not found
    """
    try:
        source = module_file.read_text()
        tree = ast.parse(source)
    except (OSError, SyntaxError) as e:
        print(f"[MUTATION] ERROR: Failed to parse {module_file}: {e}")
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == function_name:
                start_line = node.lineno
                end_line = node.end_lineno or start_line
                print(
                    f"[MUTATION] Found function '{function_name}' at lines {start_line}-{end_line}"
                )
                return start_line, end_line

    print(f"[MUTATION] WARNING: Function '{function_name}' not found in {module_file}")
    return None


async def run_mutation_testing(
    production_dir: Path,
    unit_fqn: str,
    module_path: str,
    start_line: int = 0,
    end_line: int = 0,
) -> MutationResult:
    """
    Run mutation testing on a specific function using cosmic-ray.

    Args:
        production_dir: Path to production/ directory
        unit_fqn: Fully qualified name (e.g., "pkg.module.function")
        module_path: Relative path to module (e.g., "src/pkg/module.py")
        start_line: Function start line (ignored - computed from production module)
        end_line: Function end line (ignored - computed from production module)

    Returns:
        MutationResult with score and surviving mutants
    """
    production_dir = Path(production_dir)

    # Extract function name from FQN (last part)
    function_name = unit_fqn.split(".")[-1]

    # Find actual line range by parsing the production module
    module_file = production_dir / module_path
    line_range = _find_function_line_range(module_file, function_name)

    if line_range is None:
        return MutationResult(
            success=False,
            error=f"Function '{function_name}' not found in {module_path}"
        )

    actual_start_line, actual_end_line = line_range
    print(
        f"[MUTATION] Using line range [{actual_start_line}, {actual_end_line}] "
        f"for {function_name} (passed: [{start_line}, {end_line}])"
    )

    try:
        # Get session file paths
        config_path, session_path = _get_session_paths(production_dir, unit_fqn)

        # Remove old session if exists
        if session_path.exists():
            session_path.unlink()
            print(f"[MUTATION] Removed old session: {session_path}")

        # Create config for this module
        _create_cosmic_ray_config(production_dir, module_path, config_path)

        # Step 1: Initialize session
        print("[MUTATION] Initializing cosmic-ray session...")
        init_result = _run_cosmic_ray_command(
            production_dir,
            ["init", str(config_path), str(session_path)],
            timeout=COSMIC_RAY_INIT_TIMEOUT,
        )

        if init_result.returncode != 0:
            print(f"[MUTATION] ERROR: cosmic-ray init failed: {init_result.stderr}")
            return MutationResult(
                success=False,
                error=f"cosmic-ray init failed: {init_result.stderr}"
            )

        print(f"[MUTATION] Init completed: {init_result.stdout[:500] if init_result.stdout else '(empty)'}")

        # Step 2: Execute mutations
        print("[MUTATION] Executing cosmic-ray mutations...")
        exec_result = _run_cosmic_ray_command(
            production_dir,
            ["exec", str(config_path), str(session_path)],
            timeout=COSMIC_RAY_EXEC_TIMEOUT,
        )

        print(f"[MUTATION] Exec returned: {exec_result.returncode}")
        if exec_result.stdout:
            print(f"[MUTATION] Exec stdout: {exec_result.stdout[:500]}")
        if exec_result.stderr:
            print(f"[MUTATION] WARNING: Exec stderr: {exec_result.stderr[:500]}")

        # Step 3: Dump results as JSON
        print("[MUTATION] Dumping cosmic-ray results...")
        dump_result = _run_cosmic_ray_command(
            production_dir,
            ["dump", str(session_path)],
            timeout=COSMIC_RAY_DUMP_TIMEOUT,
        )

        if dump_result.returncode != 0:
            print(f"[MUTATION] ERROR: cosmic-ray dump failed: {dump_result.stderr}")
            return MutationResult(
                success=False,
                error=f"cosmic-ray dump failed: {dump_result.stderr}"
            )

        # Parse results, filtering to function's line range
        surviving_data, total_mutants, killed_mutants = _parse_cosmic_ray_dump(
            dump_result.stdout,
            actual_start_line,
            actual_end_line,
        )

        # Handle case where no mutants were generated in the line range
        if total_mutants == 0:
            print(f"[MUTATION] WARNING: No mutants in line range [{actual_start_line}, {actual_end_line}] for {unit_fqn}")
            return MutationResult(
                success=True,
                score=1.0,  # Perfect score if no mutants
                total_mutants=0,
                killed_mutants=0,
            )

        # Build surviving mutants list with diffs
        surviving_mutants = []
        for record in surviving_data:
            mutant_id = _make_mutant_id(record)
            diff = record.get("diff", "(no diff available)")
            surviving_mutants.append(SurvivingMutant(id=mutant_id, diff=diff))

        score = killed_mutants / total_mutants if total_mutants > 0 else 1.0

        return MutationResult(
            success=True,
            score=score,
            surviving_mutants=surviving_mutants,
            total_mutants=total_mutants,
            killed_mutants=killed_mutants,
        )

    except FileNotFoundError as e:
        return MutationResult(success=False, error=str(e))
    except subprocess.TimeoutExpired as e:
        return MutationResult(
            success=False,
            error=f"Mutation testing timed out: {e}"
        )
    except Exception as e:
        print(f"[MUTATION] ERROR: {e}")
        return MutationResult(success=False, error=str(e))


async def get_mutant_diff(production_dir: Path, mutant_id: str) -> str:
    """
    Get the unified diff for a specific mutant.

    For cosmic-ray, the diff is already stored in the SurvivingMutant object
    when we parse the dump output. This function is kept for API compatibility
    but typically won't need to re-fetch the diff.

    Args:
        production_dir: Path to production/ directory
        mutant_id: The mutant ID (format: "module_path:operator:occurrence")

    Returns:
        Unified diff string showing the mutation
    """
    # Parse mutant_id to find the session
    parts = mutant_id.split(":")
    if len(parts) < 3:
        return f"(Invalid mutant ID format: {mutant_id})"

    module_path = parts[0]
    operator = parts[1]
    occurrence = int(parts[2]) if parts[2].isdigit() else 0

    production_dir = Path(production_dir)

    # Find session files - we'd need to know which unit_fqn this belongs to
    # For now, search for any session file and try to find the mutant
    mutations_dir = production_dir / ".breakfix" / "mutations"
    if not mutations_dir.exists():
        return "(No mutation sessions found)"

    for session_file in mutations_dir.glob("session_*.sqlite"):
        try:
            dump_result = _run_cosmic_ray_command(
                production_dir,
                ["dump", str(session_file)],
                timeout=COSMIC_RAY_DUMP_TIMEOUT,
            )

            if dump_result.returncode == 0:
                # Parse NDJSON format (one JSON array per line)
                for line in dump_result.stdout.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if isinstance(entry, list) and len(entry) >= 2:
                            job_info = entry[0]
                            result = entry[1]
                            mutations = job_info.get("mutations", [])
                            if mutations:
                                mutation = mutations[0]
                                if (mutation.get("module_path") == module_path and
                                    mutation.get("operator_name") == operator and
                                    mutation.get("occurrence") == occurrence):
                                    return result.get("diff", "(no diff in record)")
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"[MUTATION] WARNING: Error searching {session_file}: {e}")
            continue

    return f"(Mutant {mutant_id} not found in any session)"
