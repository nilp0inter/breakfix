"""Tests for Crucible Sentinel agent."""
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breakfix.agents.crucible.sentinel import (
    run_sentinel,
    permission_handler,
    SentinelResult,
    _calculate_test_file_path,
    SENTINEL_SYSTEM_PROMPT,
)
from breakfix.agents.crucible.mutation import SurvivingMutant
from breakfix.state import UnitWorkItem, TestCase


class TestPermissionHandler:
    """Tests for Sentinel permission_handler function."""

    def test_blocks_bash_execution(self):
        """Should deny Bash tool usage."""
        test_file = Path("/production/tests/test_core.py")
        production_dir = Path("/production")

        result = permission_handler("Bash", {"command": "pytest"}, test_file, production_dir)

        assert hasattr(result, "message")
        assert "not allowed" in result.message.lower()

    def test_blocks_bashoutput(self):
        """Should deny BashOutput tool usage."""
        test_file = Path("/production/tests/test_core.py")
        production_dir = Path("/production")

        result = permission_handler("BashOutput", {}, test_file, production_dir)

        assert hasattr(result, "message")

    def test_blocks_killbash(self):
        """Should deny KillBash tool usage."""
        test_file = Path("/production/tests/test_core.py")
        production_dir = Path("/production")

        result = permission_handler("KillBash", {}, test_file, production_dir)

        assert hasattr(result, "message")

    def test_allows_write_to_test_file(self):
        """Should allow Write to the specific test file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "tests" / "test_core.py"
            test_file.parent.mkdir(parents=True)
            test_file.touch()
            production_dir = Path(tmpdir)

            result = permission_handler(
                "Write",
                {"file_path": str(test_file)},
                test_file,
                production_dir
            )

            assert hasattr(result, "updated_input")

    def test_denies_write_to_other_files(self):
        """Should deny Write to files other than the test file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "tests" / "test_core.py"
            other_file = Path(tmpdir) / "tests" / "test_other.py"
            test_file.parent.mkdir(parents=True)
            test_file.touch()
            production_dir = Path(tmpdir)

            result = permission_handler(
                "Write",
                {"file_path": str(other_file)},
                test_file,
                production_dir
            )

            assert hasattr(result, "message")
            assert "can only write" in result.message.lower()

    def test_denies_write_to_source_files(self):
        """Should deny Write to source implementation files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "tests" / "test_core.py"
            source_file = Path(tmpdir) / "src" / "core.py"
            test_file.parent.mkdir(parents=True)
            test_file.touch()
            production_dir = Path(tmpdir)

            result = permission_handler(
                "Write",
                {"file_path": str(source_file)},
                test_file,
                production_dir
            )

            assert hasattr(result, "message")

    def test_allows_edit_to_test_file(self):
        """Should allow Edit to the specific test file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "tests" / "test_core.py"
            test_file.parent.mkdir(parents=True)
            test_file.touch()
            production_dir = Path(tmpdir)

            result = permission_handler(
                "Edit",
                {"file_path": str(test_file)},
                test_file,
                production_dir
            )

            assert hasattr(result, "updated_input")

    def test_allows_read_anywhere(self):
        """Should allow Read from any location."""
        test_file = Path("/production/tests/test_core.py")
        production_dir = Path("/production")

        result = permission_handler(
            "Read",
            {"file_path": "/production/src/core.py"},
            test_file,
            production_dir
        )

        assert hasattr(result, "updated_input")

    def test_allows_glob_anywhere(self):
        """Should allow Glob for file discovery."""
        test_file = Path("/production/tests/test_core.py")
        production_dir = Path("/production")

        result = permission_handler(
            "Glob",
            {"pattern": "**/*.py"},
            test_file,
            production_dir
        )

        assert hasattr(result, "updated_input")

    def test_allows_grep_anywhere(self):
        """Should allow Grep for searching."""
        test_file = Path("/production/tests/test_core.py")
        production_dir = Path("/production")

        result = permission_handler(
            "Grep",
            {"pattern": "def test_"},
            test_file,
            production_dir
        )

        assert hasattr(result, "updated_input")


class TestCalculateTestFilePath:
    """Tests for _calculate_test_file_path function."""

    def test_simple_unit_name(self):
        """Should handle simple unit names."""
        result = _calculate_test_file_path("module.func")

        assert result == "tests/unit/module/test_func.py"

    def test_nested_unit_name(self):
        """Should handle deeply nested unit names."""
        result = _calculate_test_file_path("pkg.subpkg.module.func")

        assert result == "tests/unit/pkg/subpkg/module/test_func.py"

    def test_private_function(self):
        """Should handle private function names."""
        result = _calculate_test_file_path("pkg.module._private_func")

        assert result == "tests/unit/pkg/module/test__private_func.py"

    def test_single_part_name(self):
        """Should handle single-part names."""
        result = _calculate_test_file_path("func")

        assert result == "tests/unit/test_func.py"


class TestSentinelResult:
    """Tests for SentinelResult dataclass."""

    def test_default_values(self):
        """Should have sensible default values."""
        result = SentinelResult(success=True)

        assert result.success is True
        assert result.test_file_path == ""
        assert result.error == ""
        assert result.retries == 0

    def test_all_fields(self):
        """Should store all fields correctly."""
        result = SentinelResult(
            success=True,
            test_file_path="tests/test_core.py",
            error="",
            retries=2,
        )

        assert result.test_file_path == "tests/test_core.py"
        assert result.retries == 2


class TestRunSentinel:
    """Tests for run_sentinel function."""

    @pytest.mark.anyio
    async def test_returns_error_when_test_file_missing(self):
        """Should return error when test file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            unit = UnitWorkItem(
                name="pkg.module.func",
                code="def func(): pass",
                module_path="src/pkg/module.py",
                description="A function",
            )
            mutant = SurvivingMutant(id="1", diff="--- a\n+++ b")

            result = await run_sentinel(
                unit=unit,
                mutant=mutant,
                production_dir=production_dir,
            )

            assert not result.success
            assert "does not exist" in result.error.lower()

    @pytest.mark.anyio
    async def test_successful_test_creation(self):
        """Should return success when test is added."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            # Create test file
            test_dir = production_dir / "tests" / "unit" / "pkg" / "module"
            test_dir.mkdir(parents=True)
            test_file = test_dir / "test_func.py"
            test_file.write_text("def test_existing(): pass\n")

            unit = UnitWorkItem(
                name="pkg.module.func",
                code="def func(x): return x + 1",
                module_path="src/pkg/module.py",
                description="Returns x + 1",
            )
            mutant = SurvivingMutant(
                id="1",
                diff="--- src/pkg/module.py\n+++ src/pkg/module.py\n-    return x + 1\n+    return x - 1"
            )

            # Mock the ClaudeSDKClient
            with patch("breakfix.agents.crucible.sentinel.ClaudeSDKClient") as MockClient:
                mock_client = AsyncMock()
                MockClient.return_value.__aenter__.return_value = mock_client
                MockClient.return_value.__aexit__.return_value = None

                # Create an async generator for receive_response
                async def simulate_response():
                    # Write new test to file (simulating agent's action)
                    test_file.write_text(
                        "def test_existing(): pass\n\n"
                        "def test_func_kills_mutant():\n"
                        "    assert func(0) == 1\n"
                    )
                    yield MagicMock()  # Some message

                # Create an async generator instance (not coroutine)
                mock_client.receive_response = MagicMock(return_value=simulate_response())

                result = await run_sentinel(
                    unit=unit,
                    mutant=mutant,
                    production_dir=production_dir,
                )

                assert result.success
                assert "test_func.py" in result.test_file_path

    @pytest.mark.anyio
    async def test_retry_when_no_test_added(self):
        """Should retry when agent doesn't add a test."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            # Create test file
            test_dir = production_dir / "tests" / "unit" / "pkg" / "module"
            test_dir.mkdir(parents=True)
            test_file = test_dir / "test_func.py"
            original_content = "def test_existing(): pass\n"
            test_file.write_text(original_content)

            unit = UnitWorkItem(
                name="pkg.module.func",
                code="def func(x): return x + 1",
                module_path="src/pkg/module.py",
                description="Returns x + 1",
            )
            mutant = SurvivingMutant(id="1", diff="diff")

            with patch("breakfix.agents.crucible.sentinel.ClaudeSDKClient") as MockClient:
                mock_client = AsyncMock()
                MockClient.return_value.__aenter__.return_value = mock_client
                MockClient.return_value.__aexit__.return_value = None

                # Create fresh generator each time receive_response is called
                def create_no_change_generator():
                    async def gen():
                        yield MagicMock()
                    return gen()

                mock_client.receive_response = MagicMock(side_effect=create_no_change_generator)
                mock_client.rewind_files = AsyncMock()

                result = await run_sentinel(
                    unit=unit,
                    mutant=mutant,
                    production_dir=production_dir,
                    max_retries=2,
                )

                assert not result.success
                assert "not modified" in result.error.lower()
                assert result.retries > 0


class TestSentinelSystemPrompt:
    """Tests for SENTINEL_SYSTEM_PROMPT constant."""

    def test_prompt_includes_key_instructions(self):
        """Should include key instructions for the agent."""
        assert "PASSES on the original" in SENTINEL_SYSTEM_PROMPT
        assert "FAILS on the mutated" in SENTINEL_SYSTEM_PROMPT
        assert "ONE" in SENTINEL_SYSTEM_PROMPT
        assert "test function" in SENTINEL_SYSTEM_PROMPT.lower()

    def test_prompt_includes_restrictions(self):
        """Should include restrictions."""
        assert "DO NOT" in SENTINEL_SYSTEM_PROMPT
        assert "create new files" in SENTINEL_SYSTEM_PROMPT.lower() or "new test files" in SENTINEL_SYSTEM_PROMPT.lower()
