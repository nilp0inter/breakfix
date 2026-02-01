import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from breakfix.graph import (
    MoveToNode,
    NodeError,
    FinalResult,
    NodeErrored,
    NodeFailed,
    run_graph,
)
from breakfix.agents import ProjectMetadata


# --- DATA STRUCTURES ---

@dataclass
class TestCase:
    id: int
    description: str
    test_function_name: str = ""  # pytest function name (e.g., "test_calculate_with_empty_list")


@dataclass
class UnitWorkItem:
    name: str                                              # FQN, e.g., "thedump.parser.parse_line"
    tests: List[TestCase] = field(default_factory=list)    # Populated by Oracle later
    code: str = ""                                         # Source code of the unit
    module_path: str = ""                                  # e.g., "/path/to/parser.py"
    line_number: int = 0                                   # Start line in module
    end_line_number: int = 0                               # End line in module
    symbol_type: str = ""                                  # "function", "class", "constant", "import"
    dependencies: List[str] = field(default_factory=list)  # Local names of dependencies
    description: str = ""                                  # Exhaustive description from Oracle


@dataclass
class ProjectState:
    user_idea: str
    working_directory: str
    spec: str = ""
    fixtures: List[Any] = field(default_factory=list)
    project_metadata: Optional[ProjectMetadata] = None
    prototype_code: str = ""
    refined_arch: str = ""
    unit_queue: List[UnitWorkItem] = field(default_factory=list)
    finished_units: List[str] = field(default_factory=list)
    interface_description: str = ""  # Description of expected I/O interface


# ==============================================================================
# OUTER GRAPH: PROJECT SCOPE
# (Spec -> Proto -> Refine -> Distill -> Unit Orchestrator)
# ==============================================================================

async def start_project_node(working_directory: str, *, deps):
    user_idea = deps.input("Enter your software idea: ")
    state = ProjectState(user_idea=user_idea, working_directory=working_directory)
    return MoveToNode.with_parameters(phase_specification_node, state)


async def phase_specification_node(state: ProjectState, *, deps):
    logging.info("[OUTER] Phase 1: Specification (Interactive Q&A)")

    # Create agent (input_fn already injected via deps.create_analyst)
    agent = deps.create_analyst()

    # Enter iter() context to maintain conversation through Q&A
    async with agent.iter(state.user_idea) as agent_run:
        async for node in agent_run:
            # Agent calls ask_user tool internally, we just iterate
            pass

        # Pydantic AI validates AnalystOutput (min 100 chars spec, min 3 fixtures)
        analyst_output = agent_run.result.output

    state.spec = analyst_output.specification
    state.fixtures = analyst_output.fixtures
    state.project_metadata = analyst_output.project
    return MoveToNode.with_parameters(phase_e2e_builder_node, state)


def _format_interface_description(interface_desc) -> str:
    """Format InterfaceDescription into a readable string for the prototyper."""
    return f"""Summary: {interface_desc.summary}
Input method: {interface_desc.input_method}
Output method: {interface_desc.output_method}
Input format: {interface_desc.input_format}
Output format: {interface_desc.output_format}
Protocol details: {interface_desc.protocol_details}
Invocation: {interface_desc.invocation}
Example interaction:
{interface_desc.example_interaction}"""


async def phase_e2e_builder_node(state: ProjectState, *, deps):
    """Create E2E test harness before scaffolding."""
    logging.info("[OUTER] Phase 1a: E2E Test Builder")

    result = await deps.run_e2e_builder(
        working_dir=state.working_directory,
        fixtures=state.fixtures,
        spec=state.spec
    )

    if not result.success:
        return NodeError(error=f"E2E builder failed: {result.error}")

    # Verify the E2E test harness works with the mock program
    logging.info("[OUTER] Phase 1a: Verifying E2E test harness")
    e2e_dir = Path(state.working_directory) / "e2e-tests"
    verification_result = await deps.run_e2e_verification(e2e_dir)

    if not verification_result.success:
        return NodeError(error=f"E2E verification failed: {verification_result.error}")

    # Analyze mock_program.py interface
    logging.info("[OUTER] Phase 1a: Analyzing mock program interface")
    mock_program_path = e2e_dir / "mock_program.py"
    mock_program_code = mock_program_path.read_text()
    interface_desc = await deps.analyze_interface(mock_program_code)
    state.interface_description = _format_interface_description(interface_desc)

    return MoveToNode.with_parameters(phase_scaffold_node, state)


async def phase_scaffold_node(state: ProjectState, *, deps):
    """Initialize project scaffold using PyScaffold."""
    logging.info("[OUTER] Phase 1b: Project Scaffolding")

    proto_dir = Path(state.working_directory) / "prototype"
    meta = state.project_metadata

    # Build putup command
    cmd = [
        "putup",
        str(proto_dir),
        "-n", meta.project_name,
        "-p", meta.package_name,
        "-d", meta.description,
        "-l", meta.license,
    ]
    if meta.url:
        cmd.extend(["-u", meta.url])
    if meta.github_actions:
        cmd.append("--github-actions")

    # Execute via deps for testability
    result = await deps.run_scaffold(cmd)

    if not result.success:
        return NodeError(error=f"Scaffolding failed: {result.error}")

    # Patch setup.cfg to add console_scripts entry point
    setup_cfg_path = proto_dir / "setup.cfg"
    _patch_setup_cfg_entrypoint(setup_cfg_path, meta.package_name)

    return MoveToNode.with_parameters(phase_prototyping_node, state)


def _patch_setup_cfg_entrypoint(setup_cfg_path: Path, package_name: str):
    """Add console_scripts entry point to setup.cfg."""
    content = setup_cfg_path.read_text()

    # Find the [options.entry_points] section and add the console_scripts
    entry_points_section = "[options.entry_points]"
    if entry_points_section in content:
        # Replace the section with one that includes the console script
        new_section = f"""{entry_points_section}
console_scripts =
    {package_name} = {package_name}.skeleton:run
"""
        # Find where the section starts and the next section begins
        start_idx = content.index(entry_points_section)
        # Find the next section (starts with [)
        rest = content[start_idx + len(entry_points_section):]
        next_section_idx = rest.find("\n[")
        if next_section_idx == -1:
            # No next section, replace to end
            content = content[:start_idx] + new_section
        else:
            # Replace up to next section
            content = content[:start_idx] + new_section + rest[next_section_idx + 1:]

        setup_cfg_path.write_text(content)


async def phase_prototyping_node(state: ProjectState, *, deps):
    """Create initial prototype implementation."""
    logging.info("[OUTER] Phase 2: Prototyping")

    result = await deps.run_prototyper(
        working_dir=state.working_directory,
        spec=state.spec,
        fixtures=state.fixtures,
        package_name=state.project_metadata.package_name,
        run_e2e_test=deps.run_prototype_e2e_test,
        interface_description=state.interface_description,
    )

    if not result.success:
        return NodeError(error=f"Prototyping failed after {result.iterations} iterations: {result.error}")

    logging.info(f"[OUTER] Prototype completed in {result.iterations} iteration(s)")
    return MoveToNode.with_parameters(phase_refinement_node, state)


async def phase_refinement_node(state: ProjectState, *, deps):
    """Phase 3: Refactor prototype into Functional Core / Imperative Shell architecture."""
    logging.info("[OUTER] Phase 3: Refinement")

    result = await deps.run_refactorer(
        working_dir=state.working_directory,
        package_name=state.project_metadata.package_name,
        run_e2e_test=deps.run_prototype_e2e_test,
        review_architecture=deps.review_architecture,
    )

    if not result.success:
        return NodeError(error=f"Refinement failed: {result.error}")

    logging.info(f"[OUTER] Refinement completed in {result.iterations} iteration(s)")
    state.refined_arch = "FCIS applied"
    return MoveToNode.with_parameters(phase_distillation_node, state)


async def phase_distillation_node(state: ProjectState, *, deps):
    """Phase 4: Decompose refined prototype into atomic units."""
    logging.info("[OUTER] Phase 4: Distillation")

    prod_dir = Path(state.working_directory) / "production"

    # Step 1: Copy prototype to production for ratchet cycle
    logging.info("[OUTER] Copying prototype to production workspace")
    copy_result = await deps.copy_prototype_to_production(
        Path(state.working_directory)
    )

    if not copy_result.success:
        return NodeError(error=f"Failed to copy prototype to production: {copy_result.error}")

    # Step 2: Run distiller to analyze production (paths will be in production/)
    result = await deps.run_distiller(
        proto_dir=prod_dir,
        package_name=state.project_metadata.package_name,
    )

    if not result.success:
        return NodeError(error=f"Distillation failed: {result.error}")

    logging.info(f"[OUTER] Distilled {len(result.units)} units")
    state.unit_queue = result.units

    # Step 3: Clean up production code for TDD (stub shell.py and core.py functions)
    logging.info("[OUTER] Cleaning up production code for TDD")
    cleanup_result = await deps.cleanup_production_code(
        unit_queue=state.unit_queue,
    )

    if not cleanup_result.success:
        return NodeError(error=f"Cleanup failed: {cleanup_result.error}")

    logging.info(f"[OUTER] Stubbed {cleanup_result.functions_stubbed} functions in {cleanup_result.files_modified} files")

    # Step 4: Filter unit_queue to only include units from stubbed files (shell.py/core.py)
    def is_tdd_target(unit: UnitWorkItem) -> bool:
        return (unit.module_path.endswith("shell.py") or
                unit.module_path.endswith("core.py"))

    all_units = len(state.unit_queue)
    state.unit_queue = [u for u in state.unit_queue if is_tdd_target(u)]
    logging.info(f"[OUTER] Filtered to {len(state.unit_queue)} TDD target units (from {all_units} total)")

    return MoveToNode.with_parameters(phase_oracle_node, state)


async def phase_oracle_node(state: ProjectState, *, deps):
    """Phase 5: Oracle - Generate test descriptions and run Ratchet for each unit."""
    logging.info("[OUTER] Phase 5: Oracle + Ratchet Cycles")

    total_tests = 0
    skipped = 0
    total_units = len(state.unit_queue)

    for i, unit in enumerate(state.unit_queue):
        logging.info(f"[ORACLE] Processing unit {i+1}/{total_units}: {unit.name}")

        # Skip non-testable units (constants, imports)
        if unit.symbol_type not in ("function", "class"):
            logging.info(f"[ORACLE] Skipped {unit.name} (symbol_type={unit.symbol_type})")
            skipped += 1
            state.finished_units.append(f"{unit.name} (Skipped - {unit.symbol_type})")
            continue

        # Generate test descriptions for this unit
        result = await deps.run_oracle(unit)

        if not result.success:
            return NodeError(error=f"Oracle failed for {unit.name}: {result.error}")

        unit.description = result.description
        unit.tests = result.test_cases
        total_tests += len(result.test_cases)

        # Log Oracle output
        logging.info(f"[ORACLE] {unit.name} - Description:")
        for line in result.description.split('\n'):
            logging.info(f"[ORACLE]   {line}")
        logging.info(f"[ORACLE] {unit.name} - Test cases ({len(result.test_cases)}):")
        for tc in result.test_cases:
            logging.info(f"[ORACLE]   [{tc.id}] {tc.description.replace(chr(10), ' | ')}")

        # Run Ratchet cycle for this unit immediately
        logging.info(f"[OUTER] Starting Ratchet cycle for: {unit.name}")
        try:
            finalized_unit_code = await run_graph(
                inner_unit_start_node,
                unit=unit,
                deps=deps
            )
            logging.info(f"[OUTER] Unit '{unit.name}' completed successfully.")
            state.finished_units.append(f"{unit.name} (Verified)")

        except NodeErrored as e:
            return NodeError(error=f"Critical failure building unit {unit.name}: {e}")
        except NodeFailed:
            raise

    logging.info(f"[OUTER] Completed {total_tests} test cases for {total_units - skipped} units ({skipped} skipped)")
    return FinalResult(result=f"Project Complete. Units: {state.finished_units}")




# ==============================================================================
# INNER GRAPH: UNIT SCOPE
# (Ratchet Loop -> Crucible Loop -> Final Code)
# ==============================================================================

async def inner_unit_start_node(unit: UnitWorkItem, *, deps):
    """Entry point for the Inner Graph"""
    return MoveToNode.with_parameters(ratchet_iterator_node, unit)


async def ratchet_iterator_node(unit: UnitWorkItem, *, deps):
    """Iterates through tests for the unit"""
    if not unit.tests:
        logging.info(f"[INNER] All tests passed for {unit.name}. Entering Crucible.")
        return MoveToNode.with_parameters(crucible_mutation_node, unit)

    current_test = unit.tests.pop(0)
    logging.info(f"[ATOMIC] Ratchet Cycle for Test: {current_test.description}")

    # Enter the Ratchet Cycle for this specific test
    return MoveToNode.with_parameters(ratchet_red_node, unit, current_test)


async def ratchet_red_node(unit: UnitWorkItem, test: TestCase, *, deps):
    """RED: Write Failing Test using Tester agent."""
    logging.info(f"[RATCHET-RED] Writing test for: {test.description[:60]}...")

    result = await deps.run_ratchet_red(
        unit=unit,
        test_case=test,
        production_dir=Path(deps.working_directory) / "production",
        get_test_inventory=deps.get_test_inventory,
    )

    if not result.success:
        logging.warning(f"[RATCHET-RED] Failed: {result.error}")
        return NodeError(error=f"Red phase failed for {unit.name}: {result.error}")

    logging.info(f"[RATCHET-RED] Test written successfully: {result.test_file_path} (retries: {result.retries})")

    # Check if Green phase should be skipped (arbiter decision)
    if result.skipped_green:
        logging.info(f"[RATCHET-RED] Skipping Green phase (arbiter decision)")
        return MoveToNode.with_parameters(ratchet_iterator_node, unit)

    # Pass pytest failure output to Green agent
    return MoveToNode.with_parameters(ratchet_green_node, unit, test, result.pytest_failure)


async def ratchet_green_node(unit: UnitWorkItem, test: TestCase, pytest_failure: str, *, deps):
    """GREEN: Write Passing Code using Developer agent."""
    logging.info(f"[RATCHET-GREEN] Implementing code for: {test.description[:60]}...")

    # Calculate the test file path (same pattern as Red agent)
    from breakfix.agents.ratchet_red.agent import _calculate_test_file_path
    test_file_path = _calculate_test_file_path(unit.name)

    result = await deps.run_ratchet_green(
        unit=unit,
        test_case=test,
        test_file_path=test_file_path,
        production_dir=Path(deps.working_directory) / "production",
        working_dir=Path(deps.working_directory),
        initial_failure=pytest_failure,
    )

    if not result.success:
        logging.warning(f"[RATCHET-GREEN] Failed: {result.error}")
        return NodeError(error=f"Green phase failed for {unit.name}: {result.error}")

    logging.info(f"[RATCHET-GREEN] Implementation complete, all tests passing (retries: {result.retries})")

    return MoveToNode.with_parameters(ratchet_iterator_node, unit)


async def crucible_mutation_node(unit: UnitWorkItem, *, deps):
    """CRUCIBLE: Mutation Testing - verify test suite completeness via mutation testing."""
    logging.info(f"[CRUCIBLE] Running mutation testing for {unit.name}")

    result = await deps.run_mutation_testing(
        production_dir=Path(deps.working_directory) / "production",
        unit_fqn=unit.name,
        module_path=unit.module_path,
        start_line=unit.line_number,
        end_line=unit.end_line_number,
    )

    if not result.success:
        return NodeError(error=f"Mutation testing failed: {result.error}")

    if result.score < 1.0:
        logging.warning(
            f"[CRUCIBLE] Mutation score {result.score:.2%}. "
            f"{len(result.surviving_mutants)} mutants survived out of {result.total_mutants}."
        )
        # Pass surviving mutants to Sentinel
        return MoveToNode.with_parameters(
            crucible_sentinel_node,
            unit,
            result.surviving_mutants,
        )

    logging.info(f"[CRUCIBLE] Perfect mutation score! All {result.total_mutants} mutants killed.")
    return MoveToNode.with_parameters(crucible_optimization_node, unit)


async def crucible_sentinel_node(unit: UnitWorkItem, surviving_mutants: list, *, deps):
    """SENTINEL: Kill surviving mutants by writing targeted tests."""
    if not surviving_mutants:
        # All mutants killed, re-verify with full mutation run
        logging.info("[SENTINEL] All mutants killed. Re-verifying...")
        return MoveToNode.with_parameters(crucible_mutation_node, unit)

    current_mutant = surviving_mutants[0]
    logging.info(f"[SENTINEL] Targeting mutant {current_mutant.id}")

    result = await deps.run_sentinel(
        unit=unit,
        mutant=current_mutant,
        production_dir=Path(deps.working_directory) / "production",
    )

    if not result.success:
        # Fatal: cannot kill mutant (possibly equivalent)
        return NodeError(
            error=f"Failed to kill mutant {current_mutant.id}: {result.error}"
        )

    # Verify the test actually kills the mutant by re-running mutmut
    logging.info(f"[SENTINEL] Verifying mutant {current_mutant.id} is killed...")
    verification = await deps.verify_mutant_killed(
        production_dir=Path(deps.working_directory) / "production",
        unit_fqn=unit.name,
        mutant_id=current_mutant.id,
        module_path=unit.module_path,
        start_line=unit.line_number,
        end_line=unit.end_line_number,
    )

    if not verification.killed:
        return NodeError(
            error=f"Sentinel test failed to kill mutant {current_mutant.id}. "
                  f"Still surviving after new test added."
        )

    logging.info(f"[SENTINEL] Mutant {current_mutant.id} killed!")

    # Continue with remaining mutants
    remaining = surviving_mutants[1:]
    if remaining:
        logging.info(f"[SENTINEL] {len(remaining)} mutants remaining")
        return MoveToNode.with_parameters(crucible_sentinel_node, unit, remaining)

    # All done, re-run mutation testing to confirm 100% score
    logging.info("[SENTINEL] All targeted mutants killed. Re-running full mutation check...")
    return MoveToNode.with_parameters(crucible_mutation_node, unit)


async def crucible_optimization_node(unit: UnitWorkItem, *, deps):
    """OPTIMIZE: Refactor"""
    optimized_code = deps.agent_optimizer(unit.name, unit.code)
    regression = deps.check_regression(optimized_code)

    if regression:
        logging.warning("[CRUCIBLE] Optimization caused regression.")
        return MoveToNode.with_parameters(crucible_optimization_node, unit)

    unit.code = optimized_code
    return FinalResult(result=unit.code)
