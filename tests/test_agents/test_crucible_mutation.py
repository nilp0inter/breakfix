"""Tests for Crucible mutation testing module (Cosmic Ray)."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

import pytest

from breakfix.agents.crucible.mutation import (
    run_mutation_testing,
    get_mutant_diff,
    _parse_cosmic_ray_dump,
    _get_cosmic_ray_path,
    _make_mutant_id,
    _create_cosmic_ray_config,
    _find_function_line_range,
    MutationResult,
    SurvivingMutant,
)


def _make_ndjson_line(module_path: str, operator: str, occurrence: int,
                       line_num: int, test_outcome: str, worker_outcome: str,
                       diff: str) -> str:
    """Helper to create a single NDJSON line in cosmic-ray dump format."""
    job_info = {
        "job_id": f"test_{occurrence}",
        "mutations": [{
            "module_path": module_path,
            "operator_name": operator,
            "occurrence": occurrence,
            "start_pos": [line_num, 0],
            "end_pos": [line_num, 10],
            "operator_args": {},
        }]
    }
    result = {
        "worker_outcome": worker_outcome,
        "test_outcome": test_outcome,
        "diff": diff,
        "output": "",
    }
    return json.dumps([job_info, result])


class TestParseCosmicRayDump:
    """Tests for parsing cosmic-ray dump NDJSON output."""

    def test_parse_single_surviving_mutant(self):
        """Should parse output with a single surviving mutant."""
        dump_output = _make_ndjson_line(
            "/path/to/pkg/core.py", "core/NumberReplacer", 0,
            15, "survived", "normal", "--- a\n+++ b"
        )
        surviving, total, killed = _parse_cosmic_ray_dump(dump_output, 10, 20)

        assert len(surviving) == 1
        assert total == 1
        assert killed == 0

    def test_parse_multiple_mutants_mixed_outcomes(self):
        """Should parse output with multiple mutants having different outcomes."""
        lines = [
            _make_ndjson_line("/path/to/pkg/core.py", "core/NumberReplacer", 0,
                              12, "killed", "normal", "diff1"),
            _make_ndjson_line("/path/to/pkg/core.py", "core/NumberReplacer", 1,
                              15, "survived", "normal", "diff2"),
            _make_ndjson_line("/path/to/pkg/core.py", "core/BooleanReplacer", 0,
                              18, "survived", "normal", "diff3"),
        ]
        dump_output = "\n".join(lines)
        surviving, total, killed = _parse_cosmic_ray_dump(dump_output, 10, 20)

        assert len(surviving) == 2
        assert total == 3
        assert killed == 1

    def test_filters_by_line_range(self):
        """Should filter mutants to only those within line range."""
        lines = [
            _make_ndjson_line("/path/to/pkg/core.py", "op1", 0,
                              5, "survived", "normal", "diff1"),  # Outside range
            _make_ndjson_line("/path/to/pkg/core.py", "op2", 0,
                              15, "survived", "normal", "diff2"),  # Inside range
            _make_ndjson_line("/path/to/pkg/core.py", "op3", 0,
                              25, "survived", "normal", "diff3"),  # Outside range
        ]
        dump_output = "\n".join(lines)
        surviving, total, killed = _parse_cosmic_ray_dump(dump_output, 10, 20)

        assert len(surviving) == 1
        assert total == 1  # Only 1 mutant in range
        assert killed == 0

    def test_counts_timeout_as_killed(self):
        """Should count timeout mutants as killed."""
        dump_output = _make_ndjson_line(
            "/path/to/pkg/core.py", "op1", 0,
            15, "", "timeout", "diff1"
        )
        surviving, total, killed = _parse_cosmic_ray_dump(dump_output, 10, 20)

        assert len(surviving) == 0
        assert total == 1
        assert killed == 1

    def test_parse_empty_output(self):
        """Should handle empty output gracefully."""
        surviving, total, killed = _parse_cosmic_ray_dump("", 10, 20)

        assert surviving == []
        assert total == 0
        assert killed == 0

    def test_parse_empty_lines(self):
        """Should handle output with only whitespace."""
        surviving, total, killed = _parse_cosmic_ray_dump("  \n  \n  ", 10, 20)

        assert surviving == []
        assert total == 0
        assert killed == 0

    def test_parse_no_survivors(self):
        """Should handle output with no surviving mutants."""
        lines = [
            _make_ndjson_line("/path/to/pkg/core.py", "op1", 0,
                              15, "killed", "normal", "diff1"),
            _make_ndjson_line("/path/to/pkg/core.py", "op2", 0,
                              16, "killed", "normal", "diff2"),
        ]
        dump_output = "\n".join(lines)
        surviving, total, killed = _parse_cosmic_ray_dump(dump_output, 10, 20)

        assert surviving == []
        assert killed == 2
        assert total == 2

    def test_parse_invalid_json_line(self):
        """Should skip invalid JSON lines gracefully."""
        lines = [
            "not json",
            _make_ndjson_line("/path/to/pkg/core.py", "op1", 0,
                              15, "survived", "normal", "diff1"),
        ]
        dump_output = "\n".join(lines)
        surviving, total, killed = _parse_cosmic_ray_dump(dump_output, 10, 20)

        # Should still parse the valid line
        assert len(surviving) == 1
        assert total == 1
        assert killed == 0


class TestMakeMutantId:
    """Tests for _make_mutant_id function."""

    def test_creates_correct_id_format(self):
        """Should create ID in module_path:operator:occurrence format."""
        record = {
            "module_path": "/path/to/pkg/module.py",
            "operator": "core/NumberReplacer",
            "occurrence": 5,
        }
        result = _make_mutant_id(record)

        assert result == "/path/to/pkg/module.py:core/NumberReplacer:5"

    def test_handles_missing_fields(self):
        """Should handle missing fields with defaults."""
        record = {}
        result = _make_mutant_id(record)

        assert result == "unknown:unknown:0"

    def test_falls_back_to_module_field(self):
        """Should fall back to module field if module_path not present."""
        record = {
            "module": "pkg.module",
            "operator": "core/NumberReplacer",
            "occurrence": 3,
        }
        result = _make_mutant_id(record)

        assert result == "pkg.module:core/NumberReplacer:3"


class TestGetCosmicRayPath:
    """Tests for getting cosmic-ray executable path."""

    def test_returns_venv_cosmic_ray_path(self):
        """Should return path to cosmic-ray in virtualenv."""
        production_dir = Path("/path/to/production")

        result = _get_cosmic_ray_path(production_dir)

        assert result == Path("/path/to/production/.venv/bin/cosmic-ray")


class TestCreateCosmicRayConfig:
    """Tests for _create_cosmic_ray_config function."""

    def test_creates_config_file(self):
        """Should create TOML config file with correct content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)
            config_path = production_dir / "config.toml"

            _create_cosmic_ray_config(
                production_dir,
                "src/pkg/module.py",
                config_path,
            )

            assert config_path.exists()
            content = config_path.read_text()
            assert 'module-path = "src/pkg/module.py"' in content
            assert "timeout = 30.0" in content
            assert "test-command" in content


class TestFindFunctionLineRange:
    """Tests for _find_function_line_range function."""

    def test_finds_simple_function(self):
        """Should find line range of a simple function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_file = Path(tmpdir) / "module.py"
            module_file.write_text('''
def foo():
    return 1

def bar():
    x = 1
    y = 2
    return x + y
''')
            result = _find_function_line_range(module_file, "bar")

            assert result is not None
            start, end = result
            assert start == 5  # def bar():
            assert end == 8    # return x + y

    def test_finds_async_function(self):
        """Should find line range of an async function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_file = Path(tmpdir) / "module.py"
            module_file.write_text('''
async def async_func():
    await something()
    return True
''')
            result = _find_function_line_range(module_file, "async_func")

            assert result is not None
            start, end = result
            assert start == 2
            assert end == 4

    def test_returns_none_for_missing_function(self):
        """Should return None if function not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_file = Path(tmpdir) / "module.py"
            module_file.write_text('''
def foo():
    return 1
''')
            result = _find_function_line_range(module_file, "nonexistent")

            assert result is None

    def test_returns_none_for_missing_file(self):
        """Should return None if file doesn't exist."""
        result = _find_function_line_range(Path("/nonexistent/module.py"), "foo")

        assert result is None

    def test_returns_none_for_syntax_error(self):
        """Should return None if file has syntax error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_file = Path(tmpdir) / "module.py"
            module_file.write_text('''
def foo(
    # missing closing paren
''')
            result = _find_function_line_range(module_file, "foo")

            assert result is None


def _create_test_module(production_dir: Path, module_path: str, function_name: str) -> None:
    """Helper to create a test module file with a function at known lines."""
    module_file = production_dir / module_path
    module_file.parent.mkdir(parents=True, exist_ok=True)
    # Create module with function at lines 10-20
    module_file.write_text(f'''# Line 1
# Line 2
# Line 3
# Line 4
# Line 5
# Line 6
# Line 7
# Line 8
# Line 9
def {function_name}():
    x = 1
    y = 2
    z = 3
    a = 4
    b = 5
    c = 6
    d = 7
    e = 8
    f = 9
    return x + y + z
''')


class TestRunMutationTesting:
    """Tests for run_mutation_testing function."""

    @pytest.mark.anyio
    async def test_returns_error_when_function_not_found(self):
        """Should return error when function not found in module."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            # Create module without the target function
            module_file = production_dir / "src/pkg/module.py"
            module_file.parent.mkdir(parents=True, exist_ok=True)
            module_file.write_text("def other_func(): pass\n")

            result = await run_mutation_testing(
                production_dir=production_dir,
                unit_fqn="pkg.module.func",
                module_path="src/pkg/module.py",
            )

            assert not result.success
            assert "not found" in result.error.lower()

    @pytest.mark.anyio
    async def test_returns_error_when_cosmic_ray_not_found(self):
        """Should return error result when cosmic-ray is not installed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            # Create module with target function
            _create_test_module(production_dir, "src/pkg/module.py", "func")

            result = await run_mutation_testing(
                production_dir=production_dir,
                unit_fqn="pkg.module.func",
                module_path="src/pkg/module.py",
            )

            assert not result.success
            assert "not found" in result.error.lower()

    @pytest.mark.anyio
    async def test_returns_perfect_score_when_no_mutants_in_range(self):
        """Should return score=1.0 when no mutants in line range."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            # Create module with target function
            _create_test_module(production_dir, "src/pkg/module.py", "func")

            # Create mock cosmic-ray executable
            venv_bin = production_dir / ".venv" / "bin"
            venv_bin.mkdir(parents=True)
            cosmic_ray_path = venv_bin / "cosmic-ray"
            cosmic_ray_path.write_text("#!/bin/bash")
            cosmic_ray_path.chmod(0o755)

            with patch("breakfix.agents.crucible.mutation._run_cosmic_ray_command") as mock_cmd:
                # Mock init, exec, dump commands
                mock_cmd.side_effect = [
                    MagicMock(returncode=0, stdout="", stderr=""),  # init
                    MagicMock(returncode=0, stdout="", stderr=""),  # exec
                    MagicMock(returncode=0, stdout="", stderr=""),  # dump (empty)
                ]

                result = await run_mutation_testing(
                    production_dir=production_dir,
                    unit_fqn="pkg.module.func",
                    module_path="src/pkg/module.py",
                )

                assert result.success
                assert result.score == 1.0
                assert result.total_mutants == 0

    @pytest.mark.anyio
    async def test_calculates_correct_score(self):
        """Should calculate correct mutation score."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            # Create module with target function (at lines 10-20)
            _create_test_module(production_dir, "src/pkg/module.py", "func")

            venv_bin = production_dir / ".venv" / "bin"
            venv_bin.mkdir(parents=True)
            cosmic_ray_path = venv_bin / "cosmic-ray"
            cosmic_ray_path.write_text("#!/bin/bash")
            cosmic_ray_path.chmod(0o755)

            # 7 killed, 3 survived = 70% score (all at line 15, within function)
            lines = [
                _make_ndjson_line("src/pkg/module.py", "op1", i,
                                  15, "killed", "normal", f"diff{i}")
                for i in range(7)
            ] + [
                _make_ndjson_line("src/pkg/module.py", "op2", i,
                                  15, "survived", "normal", f"surv_diff{i}")
                for i in range(3)
            ]
            dump_output = "\n".join(lines)

            with patch("breakfix.agents.crucible.mutation._run_cosmic_ray_command") as mock_cmd:
                mock_cmd.side_effect = [
                    MagicMock(returncode=0, stdout="", stderr=""),  # init
                    MagicMock(returncode=0, stdout="", stderr=""),  # exec
                    MagicMock(returncode=0, stdout=dump_output, stderr=""),  # dump
                ]

                result = await run_mutation_testing(
                    production_dir=production_dir,
                    unit_fqn="pkg.module.func",
                    module_path="src/pkg/module.py",
                    start_line=10,
                    end_line=20,
                )

                assert result.success
                assert result.score == 0.7  # 7/10
                assert result.total_mutants == 10
                assert result.killed_mutants == 7
                assert len(result.surviving_mutants) == 3

    @pytest.mark.anyio
    async def test_returns_error_when_init_fails(self):
        """Should return error when cosmic-ray init fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            # Create module with target function
            _create_test_module(production_dir, "src/pkg/module.py", "func")

            venv_bin = production_dir / ".venv" / "bin"
            venv_bin.mkdir(parents=True)
            cosmic_ray_path = venv_bin / "cosmic-ray"
            cosmic_ray_path.write_text("#!/bin/bash")
            cosmic_ray_path.chmod(0o755)

            with patch("breakfix.agents.crucible.mutation._run_cosmic_ray_command") as mock_cmd:
                mock_cmd.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="Init failed: some error",
                )

                result = await run_mutation_testing(
                    production_dir=production_dir,
                    unit_fqn="pkg.module.func",
                    module_path="src/pkg/module.py",
                    start_line=10,
                    end_line=20,
                )

                assert not result.success
                assert "init failed" in result.error.lower()


class TestGetMutantDiff:
    """Tests for get_mutant_diff function."""

    @pytest.mark.anyio
    async def test_returns_diff_from_session(self):
        """Should return mutant diff from cosmic-ray session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            venv_bin = production_dir / ".venv" / "bin"
            venv_bin.mkdir(parents=True)
            cosmic_ray_path = venv_bin / "cosmic-ray"
            cosmic_ray_path.write_text("#!/bin/bash")
            cosmic_ray_path.chmod(0o755)

            # Create mutations directory with session file
            mutations_dir = production_dir / ".breakfix" / "mutations"
            mutations_dir.mkdir(parents=True)
            session_file = mutations_dir / "session_pkg_module_func.sqlite"
            session_file.touch()

            expected_diff = """--- src/pkg/core.py
+++ src/pkg/core.py
@@ -10,1 +10,1 @@
-    return a + b
+    return a - b
"""
            # Use NDJSON format
            dump_output = _make_ndjson_line(
                "/path/to/pkg/module.py", "core/NumberReplacer", 5,
                10, "survived", "normal", expected_diff
            )

            with patch("breakfix.agents.crucible.mutation._run_cosmic_ray_command") as mock_cmd:
                mock_cmd.return_value = MagicMock(
                    returncode=0,
                    stdout=dump_output,
                    stderr="",
                )

                result = await get_mutant_diff(
                    production_dir,
                    "/path/to/pkg/module.py:core/NumberReplacer:5"
                )

                assert result == expected_diff

    @pytest.mark.anyio
    async def test_returns_error_when_mutant_not_found(self):
        """Should return error message when mutant ID not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            # No session files
            result = await get_mutant_diff(production_dir, "pkg.module:op:0")

            assert "not found" in result.lower() or "no mutation" in result.lower()

    @pytest.mark.anyio
    async def test_handles_invalid_mutant_id(self):
        """Should handle invalid mutant ID format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            result = await get_mutant_diff(production_dir, "invalid-id")

            assert "invalid" in result.lower()


class TestMutationResult:
    """Tests for MutationResult dataclass."""

    def test_default_values(self):
        """Should have sensible default values."""
        result = MutationResult(success=True)

        assert result.success is True
        assert result.score == 0.0
        assert result.surviving_mutants == []
        assert result.total_mutants == 0
        assert result.killed_mutants == 0
        assert result.error == ""

    def test_all_fields(self):
        """Should store all fields correctly."""
        mutants = [SurvivingMutant(id="pkg.mod:op:1", diff="diff1")]

        result = MutationResult(
            success=True,
            score=0.8,
            surviving_mutants=mutants,
            total_mutants=5,
            killed_mutants=4,
            error="",
        )

        assert result.score == 0.8
        assert result.surviving_mutants == mutants
        assert result.total_mutants == 5
        assert result.killed_mutants == 4


class TestSurvivingMutant:
    """Tests for SurvivingMutant dataclass."""

    def test_stores_id_and_diff(self):
        """Should store mutant ID and diff."""
        mutant = SurvivingMutant(
            id="pkg.module:core/NumberReplacer:42",
            diff="--- a\n+++ b"
        )

        assert mutant.id == "pkg.module:core/NumberReplacer:42"
        assert mutant.diff == "--- a\n+++ b"
