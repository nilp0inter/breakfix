"""Tests for Crucible verifier module."""
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from breakfix.agents.crucible.verifier import (
    verify_mutant_killed,
    VerificationResult,
)
from breakfix.agents.crucible.mutation import MutationResult, SurvivingMutant


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_default_values(self):
        """Should have sensible default values."""
        result = VerificationResult(killed=True)

        assert result.killed is True
        assert result.new_surviving == []
        assert result.error == ""

    def test_all_fields(self):
        """Should store all fields correctly."""
        result = VerificationResult(
            killed=False,
            new_surviving=["1", "2", "3"],
            error="Some error",
        )

        assert result.killed is False
        assert result.new_surviving == ["1", "2", "3"]
        assert result.error == "Some error"


class TestVerifyMutantKilled:
    """Tests for verify_mutant_killed function."""

    @pytest.mark.anyio
    async def test_returns_killed_true_when_mutant_not_surviving(self):
        """Should return killed=True when target mutant is no longer surviving."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            # Mock run_mutation_testing to return results WITHOUT target mutant
            mock_result = MutationResult(
                success=True,
                score=0.9,
                surviving_mutants=[SurvivingMutant(id="2", diff="diff2")],
                total_mutants=10,
                killed_mutants=9,
            )

            with patch("breakfix.agents.crucible.verifier.run_mutation_testing") as mock_run:
                mock_run.return_value = mock_result

                result = await verify_mutant_killed(
                    production_dir=production_dir,
                    unit_fqn="pkg.module.func",
                    mutant_id="1",  # Not in surviving_mutants
                )

                assert result.killed is True
                assert "1" not in result.new_surviving

    @pytest.mark.anyio
    async def test_returns_killed_false_when_mutant_still_surviving(self):
        """Should return killed=False when target mutant is still surviving."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            # Mock run_mutation_testing to return results WITH target mutant
            mock_result = MutationResult(
                success=True,
                score=0.8,
                surviving_mutants=[
                    SurvivingMutant(id="1", diff="diff1"),
                    SurvivingMutant(id="2", diff="diff2"),
                ],
                total_mutants=10,
                killed_mutants=8,
            )

            with patch("breakfix.agents.crucible.verifier.run_mutation_testing") as mock_run:
                mock_run.return_value = mock_result

                result = await verify_mutant_killed(
                    production_dir=production_dir,
                    unit_fqn="pkg.module.func",
                    mutant_id="1",  # Still in surviving_mutants
                )

                assert result.killed is False
                assert "1" in result.new_surviving
                assert "2" in result.new_surviving

    @pytest.mark.anyio
    async def test_returns_error_when_mutation_testing_fails(self):
        """Should return error when mutation testing fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            mock_result = MutationResult(
                success=False,
                error="Mutmut crashed",
            )

            with patch("breakfix.agents.crucible.verifier.run_mutation_testing") as mock_run:
                mock_run.return_value = mock_result

                result = await verify_mutant_killed(
                    production_dir=production_dir,
                    unit_fqn="pkg.module.func",
                    mutant_id="1",
                )

                assert result.killed is False
                assert "failed" in result.error.lower()

    @pytest.mark.anyio
    async def test_passes_unit_fqn_to_mutation_testing(self):
        """Should pass unit_fqn to run_mutation_testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            mock_result = MutationResult(
                success=True,
                score=1.0,
                surviving_mutants=[],
                total_mutants=5,
                killed_mutants=5,
            )

            with patch("breakfix.agents.crucible.verifier.run_mutation_testing") as mock_run:
                mock_run.return_value = mock_result

                await verify_mutant_killed(
                    production_dir=production_dir,
                    unit_fqn="pkg.module.specific_func",
                    mutant_id="1",
                    module_path="src/pkg/module.py",
                    start_line=10,
                    end_line=20,
                )

                mock_run.assert_called_once()
                call_kwargs = mock_run.call_args[1]
                assert call_kwargs["unit_fqn"] == "pkg.module.specific_func"
                assert call_kwargs["module_path"] == "src/pkg/module.py"
                assert call_kwargs["start_line"] == 10
                assert call_kwargs["end_line"] == 20

    @pytest.mark.anyio
    async def test_returns_updated_surviving_list(self):
        """Should return the updated list of surviving mutants."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            # Original had mutants 1, 2, 3 surviving
            # After test added, only 2, 3 surviving (1 was killed)
            mock_result = MutationResult(
                success=True,
                score=0.7,
                surviving_mutants=[
                    SurvivingMutant(id="2", diff="diff2"),
                    SurvivingMutant(id="3", diff="diff3"),
                ],
                total_mutants=10,
                killed_mutants=7,
            )

            with patch("breakfix.agents.crucible.verifier.run_mutation_testing") as mock_run:
                mock_run.return_value = mock_result

                result = await verify_mutant_killed(
                    production_dir=production_dir,
                    unit_fqn="pkg.module.func",
                    mutant_id="1",
                )

                assert result.killed is True
                assert result.new_surviving == ["2", "3"]

    @pytest.mark.anyio
    async def test_handles_perfect_score(self):
        """Should handle case where all mutants are killed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            production_dir = Path(tmpdir)

            mock_result = MutationResult(
                success=True,
                score=1.0,
                surviving_mutants=[],
                total_mutants=10,
                killed_mutants=10,
            )

            with patch("breakfix.agents.crucible.verifier.run_mutation_testing") as mock_run:
                mock_run.return_value = mock_result

                result = await verify_mutant_killed(
                    production_dir=production_dir,
                    unit_fqn="pkg.module.func",
                    mutant_id="5",
                )

                assert result.killed is True
                assert result.new_surviving == []
