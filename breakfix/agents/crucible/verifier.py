"""Verification that Sentinel's test actually kills a mutant."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .mutation import run_mutation_testing

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result from verifying that a mutant was killed."""
    killed: bool  # True if mutant_id no longer in surviving list
    new_surviving: list[str] = field(default_factory=list)  # Updated surviving IDs
    error: str = ""


async def verify_mutant_killed(
    production_dir: Path,
    unit_fqn: str,
    mutant_id: str,
    module_path: str = "",
    start_line: int = 0,
    end_line: int = 0,
) -> VerificationResult:
    """
    Verify that a mutant was killed by re-running mutation testing.

    After the Sentinel adds a new test, we re-run mutmut to check if
    the target mutant is still in the surviving list.

    Args:
        production_dir: Path to production/ directory
        unit_fqn: Fully qualified name of the unit
        mutant_id: The specific mutant ID to check
        module_path: Relative path to module (optional, for full re-run)
        start_line: Function start line (optional)
        end_line: Function end line (optional)

    Returns:
        VerificationResult indicating if the mutant was killed
    """
    production_dir = Path(production_dir)

    try:
        logger.info(f"[VERIFIER] Re-running mutation testing to verify mutant {mutant_id} is killed")

        # Re-run mutation testing with the new test in place
        result = await run_mutation_testing(
            production_dir=production_dir,
            unit_fqn=unit_fqn,
            module_path=module_path,
            start_line=start_line,
            end_line=end_line,
        )

        if not result.success:
            return VerificationResult(
                killed=False,
                error=f"Mutation testing failed during verification: {result.error}"
            )

        # Check if target mutant is still surviving
        surviving_ids = [m.id for m in result.surviving_mutants]
        killed = mutant_id not in surviving_ids

        if killed:
            logger.info(f"[VERIFIER] Mutant {mutant_id} successfully killed!")
        else:
            logger.warning(f"[VERIFIER] Mutant {mutant_id} still surviving")

        return VerificationResult(
            killed=killed,
            new_surviving=surviving_ids,
        )

    except Exception as e:
        logger.error(f"[VERIFIER] Error during verification: {e}")
        return VerificationResult(
            killed=False,
            error=str(e),
        )
