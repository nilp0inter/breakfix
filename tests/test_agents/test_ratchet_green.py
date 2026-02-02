"""Tests for Ratchet Green Phase (Developer Agent) functionality."""
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breakfix.agents.ratchet_green.agent import (
    run_ratchet_green,
    RatchetGreenResult,
    PytestResult,
    permission_handler,
    run_pytest,
    DEVELOPER_SYSTEM_PROMPT,
)
from breakfix.state import UnitWorkItem, TestCase


class TestPermissionHandler:
    """Tests for permission_handler function."""

    def test_blocks_bash_execution(self):
        """Should deny Bash tool usage."""
        unit_file = Path("/production/src/mypackage/core.py")
        test_file = Path("/production/tests/unit/mypackage/test_core.py")

        result = permission_handler("Bash", {"command": "pytest"}, unit_file, test_file)

        assert hasattr(result, "message")
        assert "not allowed" in result.message.lower()

    def test_blocks_bashoutput(self):
        """Should deny BashOutput tool usage."""
        unit_file = Path("/production/src/mypackage/core.py")
        test_file = Path("/production/tests/unit/mypackage/test_core.py")

        result = permission_handler("BashOutput", {}, unit_file, test_file)

        assert hasattr(result, "message")

    def test_allows_write_to_unit_file(self):
        """Should allow Write to unit implementation file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            unit_file = Path(tmpdir) / "src" / "mypackage" / "core.py"
            test_file = Path(tmpdir) / "tests" / "test_core.py"

            result = permission_handler("Write", {"file_path": str(unit_file)}, unit_file, test_file)

            assert hasattr(result, "updated_input")

    def test_denies_write_to_other_file(self):
        """Should deny Write to files other than unit file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            unit_file = Path(tmpdir) / "src" / "mypackage" / "core.py"
            test_file = Path(tmpdir) / "tests" / "test_core.py"
            other_file = Path(tmpdir) / "src" / "mypackage" / "shell.py"

            result = permission_handler("Write", {"file_path": str(other_file)}, unit_file, test_file)

            assert hasattr(result, "message")
            assert "only allowed" in result.message.lower()

    def test_denies_read_test_file(self):
        """Should deny Read access to the test file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            unit_file = Path(tmpdir) / "src" / "mypackage" / "core.py"
            test_file = Path(tmpdir) / "tests" / "test_core.py"

            result = permission_handler("Read", {"file_path": str(test_file)}, unit_file, test_file)

            assert hasattr(result, "message")
            assert "access denied" in result.message.lower()

    def test_denies_write_test_file(self):
        """Should deny Write access to the test file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            unit_file = Path(tmpdir) / "src" / "mypackage" / "core.py"
            test_file = Path(tmpdir) / "tests" / "test_core.py"

            result = permission_handler("Write", {"file_path": str(test_file)}, unit_file, test_file)

            assert hasattr(result, "message")
            # Will be denied either for being test file or not being unit file
            assert "denied" in result.message.lower() or "only allowed" in result.message.lower()

    def test_allows_read_other_source_files(self):
        """Should allow Read from other source files (not tests)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            unit_file = Path(tmpdir) / "src" / "mypackage" / "core.py"
            test_file = Path(tmpdir) / "tests" / "test_core.py"
            other_file = Path(tmpdir) / "src" / "mypackage" / "utils.py"

            result = permission_handler("Read", {"file_path": str(other_file)}, unit_file, test_file)

            assert hasattr(result, "updated_input")

    def test_allows_glob(self):
        """Should allow Glob tool."""
        unit_file = Path("/production/src/mypackage/core.py")
        test_file = Path("/production/tests/test_core.py")

        result = permission_handler("Glob", {"pattern": "**/*.py"}, unit_file, test_file)

        assert hasattr(result, "updated_input")

    def test_allows_grep(self):
        """Should allow Grep tool."""
        unit_file = Path("/production/src/mypackage/core.py")
        test_file = Path("/production/tests/test_core.py")

        result = permission_handler("Grep", {"pattern": "def "}, unit_file, test_file)

        assert hasattr(result, "updated_input")


class TestRatchetGreenResult:
    """Tests for RatchetGreenResult dataclass."""

    def test_success_result(self):
        """Should create a success result."""
        result = RatchetGreenResult(
            success=True,
            retries=2,
        )

        assert result.success
        assert result.error == ""
        assert result.retries == 2

    def test_failure_result(self):
        """Should create a failure result with error."""
        result = RatchetGreenResult(
            success=False,
            error="Tests still failing",
            retries=5,
        )

        assert not result.success
        assert "Tests still failing" in result.error
        assert result.retries == 5

    def test_default_values(self):
        """Should have correct default values."""
        result = RatchetGreenResult(success=True)

        assert result.success
        assert result.error == ""
        assert result.retries == 0


class TestPytestResult:
    """Tests for PytestResult dataclass."""

    def test_success_result(self):
        """Should create a success result."""
        result = PytestResult(success=True, output="All tests passed")

        assert result.success
        assert "passed" in result.output

    def test_failure_result(self):
        """Should create a failure result."""
        result = PytestResult(success=False, output="AssertionError: expected 5, got 3")

        assert not result.success
        assert "AssertionError" in result.output


class TestRunPytest:
    """Tests for run_pytest function."""

    def test_returns_success_on_passing_tests(self):
        """Should return success when pytest passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            venv_dir = tmpdir / ".venv" / "bin"
            venv_dir.mkdir(parents=True)
            tests_dir = tmpdir / "tests"
            tests_dir.mkdir()

            # Create a mock pytest executable
            pytest_path = venv_dir / "pytest"
            pytest_path.write_text("#!/bin/bash\nexit 0")
            pytest_path.chmod(0o755)

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="1 passed",
                    stderr=""
                )

                result = run_pytest(tmpdir)

            assert result.success
            assert "passed" in result.output

    def test_returns_failure_on_failing_tests(self):
        """Should return failure when pytest fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="FAILED test_core.py::test_calculate",
                    stderr=""
                )

                result = run_pytest(tmpdir)

            assert not result.success
            assert "FAILED" in result.output


class TestDeveloperSystemPrompt:
    """Tests for DEVELOPER_SYSTEM_PROMPT."""

    def test_prompt_mentions_minimal_code(self):
        """Should mention implementing minimal code."""
        assert "minimal" in DEVELOPER_SYSTEM_PROMPT.lower()

    def test_prompt_mentions_not_over_engineer(self):
        """Should warn against over-engineering."""
        assert "over-engineer" in DEVELOPER_SYSTEM_PROMPT.lower()

    def test_prompt_mentions_not_reading_tests(self):
        """Should warn against reading test files."""
        assert "not read" in DEVELOPER_SYSTEM_PROMPT.lower() or "do not read" in DEVELOPER_SYSTEM_PROMPT.lower()

    def test_prompt_mentions_tdd(self):
        """Should mention TDD principles."""
        assert "tdd" in DEVELOPER_SYSTEM_PROMPT.lower()


# ============================================================================
# Coverage Check Tests
# ============================================================================

from breakfix.agents.ratchet_green.coverage import (
    check_coverage_intersection,
    get_baseline_path,
    load_baseline,
    save_baseline,
    format_coverage_feedback,
    run_pytest_with_coverage,
    CoverageCheckResult,
)


class TestCheckCoverageIntersection:
    """Tests for check_coverage_intersection function."""

    def test_detects_dead_code_in_function_range(self):
        """Should detect missing lines within the function range."""
        coverage_data = {
            "files": {
                "src/pkg/core.py": {
                    "executed_lines": [1, 2, 5, 6, 10, 11],
                    "missing_lines": [7, 8, 9, 15, 16],
                }
            }
        }

        # Function is lines 5-12
        dead_code = check_coverage_intersection(coverage_data, "src/pkg/core.py", 5, 12)

        # Lines 7, 8, 9 are in range and missing
        assert dead_code == {7, 8, 9}

    def test_no_dead_code_when_all_covered(self):
        """Should return empty set when all lines in range are covered."""
        coverage_data = {
            "files": {
                "src/pkg/core.py": {
                    "executed_lines": [5, 6, 7, 8, 9, 10],
                    "missing_lines": [1, 2, 15, 16],
                }
            }
        }

        dead_code = check_coverage_intersection(coverage_data, "src/pkg/core.py", 5, 10)

        assert dead_code == set()

    def test_handles_missing_file(self):
        """Should return empty set when file not found in coverage data."""
        coverage_data = {
            "files": {
                "src/pkg/other.py": {
                    "executed_lines": [1, 2, 3],
                    "missing_lines": [],
                }
            }
        }

        dead_code = check_coverage_intersection(coverage_data, "src/pkg/core.py", 5, 10)

        assert dead_code == set()

    def test_matches_file_by_suffix(self):
        """Should match file when paths have different prefixes."""
        coverage_data = {
            "files": {
                "/absolute/path/to/src/pkg/core.py": {
                    "executed_lines": [1, 2, 3],
                    "missing_lines": [5, 6],
                }
            }
        }

        dead_code = check_coverage_intersection(coverage_data, "src/pkg/core.py", 1, 6)

        assert dead_code == {5, 6}

    def test_empty_coverage_data(self):
        """Should handle empty coverage data gracefully."""
        coverage_data = {"files": {}}

        dead_code = check_coverage_intersection(coverage_data, "src/pkg/core.py", 5, 10)

        assert dead_code == set()


class TestBaselinePersistence:
    """Tests for coverage baseline load/save functions."""

    def test_get_baseline_path_sanitizes_fqn(self):
        """Should sanitize FQN for filesystem-safe path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = get_baseline_path(Path(tmpdir), "pkg.module.function")

            assert path.name == "pkg_module_function.json"
            assert ".breakfix" in str(path)
            assert "coverage" in str(path)

    def test_load_baseline_returns_none_when_missing(self):
        """Should return None when baseline file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = load_baseline(Path(tmpdir), "pkg.module.function")

            assert result is None

    def test_save_and_load_baseline_roundtrip(self):
        """Should persist and restore baseline correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            coverage_data = {
                "files": {
                    "src/pkg/core.py": {
                        "executed_lines": [5, 6, 7, 10, 11],
                        "missing_lines": [],
                    }
                }
            }

            save_baseline(
                Path(tmpdir),
                "pkg.core.my_func",
                coverage_data,
                "src/pkg/core.py",
                start_line=5,
                end_line=12,
            )

            loaded = load_baseline(Path(tmpdir), "pkg.core.my_func")

            # Only lines 5-12 that were executed should be in baseline
            assert loaded == {5, 6, 7, 10, 11}

    def test_save_baseline_creates_directories(self):
        """Should create necessary directories when saving baseline."""
        with tempfile.TemporaryDirectory() as tmpdir:
            coverage_data = {
                "files": {
                    "src/pkg/core.py": {
                        "executed_lines": [1, 2, 3],
                        "missing_lines": [],
                    }
                }
            }

            # Directories don't exist yet
            save_baseline(
                Path(tmpdir),
                "pkg.core.my_func",
                coverage_data,
                "src/pkg/core.py",
                start_line=1,
                end_line=3,
            )

            # Should have created the file
            baseline_path = get_baseline_path(Path(tmpdir), "pkg.core.my_func")
            assert baseline_path.exists()


class TestFormatCoverageFeedback:
    """Tests for format_coverage_feedback function."""

    def test_includes_line_numbers(self):
        """Should include dead code line numbers in feedback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)
            source_dir = production_dir / "src" / "pkg"
            source_dir.mkdir(parents=True)
            source_file = source_dir / "core.py"
            source_file.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n")

            feedback = format_coverage_feedback(
                {3, 4},
                "src/pkg/core.py",
                production_dir,
            )

            assert "3" in feedback
            assert "4" in feedback
            assert "line 3" in feedback
            assert "line 4" in feedback

    def test_includes_instructions(self):
        """Should include instructions for fixing dead code."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feedback = format_coverage_feedback(
                {5},
                "src/pkg/core.py",
                Path(tmpdir),
            )

            assert "dead code" in feedback.lower()
            assert "remove" in feedback.lower() or "simplify" in feedback.lower()

    def test_mentions_module_path(self):
        """Should mention the module path in feedback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feedback = format_coverage_feedback(
                {5},
                "src/pkg/core.py",
                Path(tmpdir),
            )

            assert "src/pkg/core.py" in feedback


class TestRunPytestWithCoverage:
    """Tests for run_pytest_with_coverage function."""

    def test_returns_coverage_data_on_success(self):
        """Should return coverage data when pytest succeeds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)
            venv_dir = production_dir / ".venv" / "bin"
            venv_dir.mkdir(parents=True)
            tests_dir = production_dir / "tests"
            tests_dir.mkdir()

            coverage_json = production_dir / "coverage.json"

            # Mock subprocess.run to simulate pytest creating the coverage file
            def mock_subprocess_run(*args, **kwargs):
                # Simulate pytest-cov creating the coverage file (default output is coverage.json)
                coverage_json.write_text('{"files": {"src/core.py": {"executed_lines": [1,2,3], "missing_lines": []}}}')
                return MagicMock(
                    returncode=0,
                    stdout="1 passed",
                    stderr=""
                )

            with patch("subprocess.run", side_effect=mock_subprocess_run):
                success, coverage_data, output = run_pytest_with_coverage(
                    production_dir,
                    "src/core.py"
                )

            assert success
            assert coverage_data is not None
            assert "files" in coverage_data
            assert "passed" in output

    def test_returns_none_when_no_coverage_file(self):
        """Should return None for coverage data when file not created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="1 passed",
                    stderr=""
                )

                success, coverage_data, output = run_pytest_with_coverage(
                    production_dir,
                    "src/core.py"
                )

            assert success
            assert coverage_data is None


class TestCoverageCheckResult:
    """Tests for CoverageCheckResult dataclass."""

    def test_success_result(self):
        """Should create a success result with no dead code."""
        result = CoverageCheckResult(success=True)

        assert result.success
        assert result.dead_code_lines == set()
        assert result.error == ""

    def test_failure_result_with_dead_code(self):
        """Should create a failure result with dead code lines."""
        result = CoverageCheckResult(
            success=False,
            dead_code_lines={5, 6, 7},
            error="Dead code detected"
        )

        assert not result.success
        assert result.dead_code_lines == {5, 6, 7}
        assert "Dead code" in result.error
