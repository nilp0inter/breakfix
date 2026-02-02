"""Prefect artifact helpers for BreakFix pipeline visibility."""

from typing import TYPE_CHECKING

from prefect.artifacts import (
    create_markdown_artifact,
    create_table_artifact,
    create_progress_artifact,
    update_progress_artifact,
)

if TYPE_CHECKING:
    from breakfix.state import ProjectState, UnitWorkItem, TestCase
    from breakfix.agents.crucible import MutationResult, SurvivingMutant


def sanitize_key(name: str) -> str:
    """Convert name to valid artifact key (lowercase, dashes only)."""
    return name.lower().replace(".", "-").replace("_", "-")


# =============================================================================
# Phase 1: Specification
# =============================================================================


async def specification_artifacts(state: "ProjectState") -> None:
    """Create artifacts for specification phase."""
    # Spec document
    await create_markdown_artifact(
        markdown=f"# Specification\n\n{state.spec}",
        key="spec-document",
        description="Software specification from analyst",
    )

    # Fixtures table
    fixtures_data = [
        {
            "ID": i + 1,
            "Name": f.name,
            "Description": f.description,
            "Input": str(f.input_data)[:50],
            "Expected": str(f.expected_output)[:50],
        }
        for i, f in enumerate(state.fixtures)
    ]
    await create_table_artifact(
        table=fixtures_data,
        key="test-fixtures",
        description="Test fixtures for validation",
    )

    # Project metadata
    if state.project_metadata:
        pm = state.project_metadata
        md = f"""# Project Metadata

| Field | Value |
|-------|-------|
| Project Name | {pm.project_name} |
| Package Name | {pm.package_name} |
| Description | {pm.description} |
| License | {pm.license} |
| URL | {pm.url or 'N/A'} |
| GitHub Actions | {'Yes' if pm.github_actions else 'No'} |
"""
        await create_markdown_artifact(
            markdown=md,
            key="project-metadata",
            description="PyScaffold project configuration",
        )


# =============================================================================
# Phase 1a: E2E Builder
# =============================================================================


async def e2e_builder_artifacts(interface_description: str, verification_passed: bool) -> None:
    """Create artifacts for E2E builder phase."""
    # Interface description
    await create_markdown_artifact(
        markdown=f"# Interface Description\n\n{interface_description}",
        key="interface-description",
        description="Expected I/O interface for the program",
    )

    # Verification status
    status = "PASSED" if verification_passed else "FAILED"
    status_emoji = "+" if verification_passed else "-"
    md = f"""# E2E Verification

```diff
{status_emoji} Mock program verification: {status}
```
"""
    await create_markdown_artifact(
        markdown=md,
        key="e2e-verification",
        description="E2E test verification result",
    )


# =============================================================================
# Phase 1b: Scaffold
# =============================================================================


async def scaffold_artifacts(command: list[str], success: bool) -> None:
    """Create artifacts for scaffold phase."""
    cmd_str = " ".join(command)
    status = "SUCCESS" if success else "FAILED"

    md = f"""# PyScaffold Initialization

**Status:** {status}

**Command:**
```bash
{cmd_str}
```
"""
    await create_markdown_artifact(
        markdown=md,
        key="scaffold-command",
        description="PyScaffold putup command executed",
    )


# =============================================================================
# Phase 2: Prototyping
# =============================================================================


async def prototyping_progress_start(max_iterations: int) -> str:
    """Create initial progress artifact for prototyping. Returns artifact ID."""
    artifact_id = await create_progress_artifact(
        progress=0.0,
        key="prototyping-progress",
        description=f"Prototype implementation (max {max_iterations} iterations)",
    )
    return str(artifact_id)


async def prototyping_progress_update(artifact_id: str, iteration: int, max_iterations: int) -> None:
    """Update prototyping progress artifact."""
    progress = (iteration / max_iterations) * 100
    await update_progress_artifact(artifact_id=artifact_id, progress=progress)


async def prototyping_result_artifact(iterations: int, success: bool, error: str = "") -> None:
    """Create final prototyping result artifact."""
    status = "SUCCESS" if success else "FAILED"

    md = f"""# Prototyping Result

| Metric | Value |
|--------|-------|
| Status | {status} |
| Iterations | {iterations} |
"""
    if error:
        md += f"\n**Error:**\n```\n{error[:500]}\n```"

    await create_markdown_artifact(
        markdown=md,
        key="prototyping-result",
        description="Prototype implementation result",
    )


# =============================================================================
# Phase 3: Refinement
# =============================================================================


async def refinement_progress_start(max_iterations: int) -> str:
    """Create initial progress artifact for refinement. Returns artifact ID."""
    artifact_id = await create_progress_artifact(
        progress=0.0,
        key="refinement-progress",
        description=f"FCIS refactoring (max {max_iterations} iterations)",
    )
    return str(artifact_id)


async def refinement_progress_update(artifact_id: str, iteration: int, max_iterations: int) -> None:
    """Update refinement progress artifact."""
    progress = (iteration / max_iterations) * 100
    await update_progress_artifact(artifact_id=artifact_id, progress=progress)


async def refinement_result_artifact(iterations: int, success: bool) -> None:
    """Create final refinement result artifact."""
    status = "SUCCESS" if success else "FAILED"

    md = f"""# Refinement Result (FCIS)

| Metric | Value |
|--------|-------|
| Status | {status} |
| Iterations | {iterations} |
| Architecture | Functional Core / Imperative Shell |
"""
    await create_markdown_artifact(
        markdown=md,
        key="refinement-result",
        description="FCIS refactoring result",
    )


# =============================================================================
# Phase 4: Distillation
# =============================================================================


async def distillation_artifacts(
    unit_queue: list["UnitWorkItem"],
    total_units: int,
    tdd_targets: int,
    functions_stubbed: int,
    files_modified: int,
) -> None:
    """Create artifacts for distillation phase."""
    # Unit inventory table
    inventory = [
        {
            "Name": u.name,
            "Type": u.symbol_type,
            "Module": u.module_path.split("/")[-1] if u.module_path else "",
            "Lines": f"{u.line_number}-{u.end_line_number}" if u.line_number else "N/A",
            "Deps": len(u.dependencies),
        }
        for u in unit_queue
    ]
    await create_table_artifact(
        table=inventory,
        key="unit-inventory",
        description="Units to reconstruct via TDD",
    )

    # Stats
    filter_pct = (tdd_targets / total_units * 100) if total_units > 0 else 0
    md = f"""# Distillation Statistics

| Metric | Value |
|--------|-------|
| Total Units | {total_units} |
| TDD Targets | {tdd_targets} |
| Filter Rate | {filter_pct:.1f}% |
| Functions Stubbed | {functions_stubbed} |
| Files Modified | {files_modified} |
"""
    await create_markdown_artifact(
        markdown=md,
        key="distillation-stats",
        description="Code decomposition statistics",
    )


# =============================================================================
# Phase 4.5: Oracle
# =============================================================================


async def oracle_artifacts(
    unit_name: str,
    description: str,
    test_cases: list["TestCase"],
) -> None:
    """Create artifacts for oracle phase."""
    key_base = sanitize_key(unit_name)

    # Unit description
    await create_markdown_artifact(
        markdown=f"# {unit_name}\n\n{description}",
        key=f"oracle-{key_base}-description",
        description=f"Unit description for {unit_name}",
    )

    # Test cases table
    if test_cases:
        cases_data = [
            {
                "ID": tc.id,
                "Description": tc.description[:100] if tc.description else "",
            }
            for tc in test_cases
        ]
        await create_table_artifact(
            table=cases_data,
            key=f"oracle-{key_base}-tests",
            description=f"Test cases for {unit_name}",
        )


# =============================================================================
# Phase 5: Ratchet Red
# =============================================================================


async def ratchet_red_artifacts(
    unit_name: str,
    test_id: int,
    test_description: str,
    pytest_output: str,
    retries: int,
    skip_green: bool,
) -> None:
    """Create artifacts for ratchet red phase."""
    key_base = sanitize_key(unit_name)

    status = "SKIP GREEN" if skip_green else "PROCEED TO GREEN"

    md = f"""# Ratchet Red: {unit_name} (Test {test_id})

**Test Description:** {test_description}

**Status:** {status}
**Retries:** {retries}

**Pytest Output:**
```
{pytest_output[:1000]}
```
"""
    await create_markdown_artifact(
        markdown=md,
        key=f"ratchet-red-{key_base}-{test_id}",
        description=f"Red phase for {unit_name} test {test_id}",
    )


# =============================================================================
# Phase 5: Ratchet Green
# =============================================================================


async def ratchet_green_artifacts(
    unit_name: str,
    test_id: int,
    retries: int,
    success: bool,
) -> None:
    """Create artifacts for ratchet green phase."""
    key_base = sanitize_key(unit_name)
    status = "PASSED" if success else "FAILED"

    md = f"""# Ratchet Green: {unit_name} (Test {test_id})

| Metric | Value |
|--------|-------|
| Status | {status} |
| Retries | {retries} |
"""
    await create_markdown_artifact(
        markdown=md,
        key=f"ratchet-green-{key_base}-{test_id}",
        description=f"Green phase for {unit_name} test {test_id}",
    )


# =============================================================================
# Phase 7: Mutation Testing
# =============================================================================


async def mutation_artifacts(
    unit_name: str,
    score: float,
    total_mutants: int,
    surviving_mutants: list["SurvivingMutant"],
) -> None:
    """Create artifacts for mutation testing phase."""
    key_base = sanitize_key(unit_name)

    # Score summary
    score_pct = score * 100
    killed = total_mutants - len(surviving_mutants)

    md = f"""# Mutation Testing: {unit_name}

| Metric | Value |
|--------|-------|
| Score | {score_pct:.1f}% |
| Total Mutants | {total_mutants} |
| Killed | {killed} |
| Surviving | {len(surviving_mutants)} |
"""
    await create_markdown_artifact(
        markdown=md,
        key=f"mutation-{key_base}-score",
        description=f"Mutation score for {unit_name}",
    )

    # Surviving mutants table (if any)
    if surviving_mutants:
        survivors = [{"ID": m.id, "Description": m.description} for m in surviving_mutants]
        await create_table_artifact(
            table=survivors,
            key=f"mutation-{key_base}-survivors",
            description=f"Surviving mutants for {unit_name}",
        )


# =============================================================================
# Phase 7: Sentinel
# =============================================================================


async def sentinel_artifacts(
    unit_name: str,
    mutant_id: str,
    mutant_killed: bool,
) -> None:
    """Create artifacts for sentinel phase."""
    key_base = sanitize_key(unit_name)
    mutant_key = sanitize_key(mutant_id)
    status = "KILLED" if mutant_killed else "SURVIVED"

    md = f"""# Sentinel: {unit_name}

**Mutant ID:** {mutant_id}
**Status:** {status}
"""
    await create_markdown_artifact(
        markdown=md,
        key=f"sentinel-{key_base}-{mutant_key}",
        description=f"Sentinel result for mutant {mutant_id}",
    )


# =============================================================================
# Phase 7: Optimization
# =============================================================================


async def optimization_artifacts(unit_name: str, success: bool) -> None:
    """Create artifacts for optimization phase."""
    key_base = sanitize_key(unit_name)
    status = "COMPLETE" if success else "SKIPPED"

    md = f"""# Optimization: {unit_name}

**Status:** {status}
"""
    await create_markdown_artifact(
        markdown=md,
        key=f"optimization-{key_base}",
        description=f"Optimization result for {unit_name}",
    )
