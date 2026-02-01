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
from breakfix.nodes import UnitWorkItem, TestCase


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
