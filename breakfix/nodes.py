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


@dataclass
class UnitWorkItem:
    name: str
    tests: List[TestCase]
    code: str = ""  # Stores the evolving code for this unit


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
    raise NotImplementedError
    logging.info("[OUTER] Phase 3: Refinement")
    refined_code = deps.agent_architect(state.prototype_code)
    is_clean, msg = deps.check_architectural_taint(refined_code)

    if not is_clean:
        logging.warning(f"Arch Violation: {msg}")
        return MoveToNode.with_parameters(phase_refinement_node, state)

    state.refined_arch = refined_code
    return MoveToNode.with_parameters(phase_distillation_node, state)


async def phase_distillation_node(state: ProjectState, *, deps):
    logging.info("[OUTER] Phase 4: Distillation")
    units = deps.process_dependency_graph(state.refined_arch)
    state.unit_queue = units
    return MoveToNode.with_parameters(unit_orchestrator_node, state)


async def unit_orchestrator_node(state: ProjectState, *, deps):
    """
    META-NODE: This node stops the flat flow and invokes a
    recursive graph execution for each unit.
    """
    if not state.unit_queue:
        return FinalResult(result=f"Project Complete. Units: {state.finished_units}")

    # Pop the next unit to build
    current_unit = state.unit_queue.pop(0)
    logging.info(f"[OUTER] Delegating Unit '{current_unit.name}' to Inner Graph.")

    try:
        # RECURSION TRIGGER: Calls run_graph inside run_graph
        # The inner graph handles the complex Ratchet/Crucible lifecycles
        finalized_unit_code = await run_graph(
            inner_unit_start_node,
            unit=current_unit,
            deps=deps
        )

        logging.info(f"[OUTER] Unit '{current_unit.name}' completed successfully.")
        state.finished_units.append(f"{current_unit.name} (Verified)")

        # Loop back to self to handle next unit in queue
        return MoveToNode.with_parameters(unit_orchestrator_node, state)

    except (NodeErrored, NodeFailed) as e:
        return NodeError(error=f"Critical failure building unit {current_unit.name}: {e}")


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
    """RED: Write Failing Test"""
    # In real logic, we'd append to unit.code or test suite files
    test_code = deps.agent_tester(unit.name, test.description)
    valid_red = deps.check_ratchet_red_state(test_code)

    if not valid_red:
        logging.warning("[ATOMIC] Red Check Failed. Retrying.")
        return MoveToNode.with_parameters(ratchet_red_node, unit, test)

    return MoveToNode.with_parameters(ratchet_green_node, unit, test)


async def ratchet_green_node(unit: UnitWorkItem, test: TestCase, *, deps):
    """GREEN: Write Passing Code"""
    impl_code = deps.agent_developer(unit.name, test.description)
    valid_green = deps.check_ratchet_green_coverage(impl_code)

    if not valid_green:
        logging.warning("[ATOMIC] Green/Coverage Check Failed. Retrying.")
        return MoveToNode.with_parameters(ratchet_green_node, unit, test)

    # Commit code to unit state
    unit.code += f"\n# Impl for {test.description}"
    return MoveToNode.with_parameters(ratchet_iterator_node, unit)


async def crucible_mutation_node(unit: UnitWorkItem, *, deps):
    """CRUCIBLE: Mutation Testing"""
    score = deps.process_mutation_testing(unit.name)
    if score < 1.0:
        logging.warning(f"[CRUCIBLE] Mutation Score {score}. Deploying Sentinel.")
        return MoveToNode.with_parameters(crucible_sentinel_node, unit)

    return MoveToNode.with_parameters(crucible_optimization_node, unit)


async def crucible_sentinel_node(unit: UnitWorkItem, *, deps):
    """SENTINEL: Kill Mutants"""
    new_test = deps.agent_sentinel(unit.name)
    killed = deps.check_mutant_killed(new_test)

    if killed:
        logging.info("[CRUCIBLE] Mutant killed.")
        # Re-run mutation check
        return MoveToNode.with_parameters(crucible_mutation_node, unit)
    else:
        logging.warning("[CRUCIBLE] Failed to kill mutant. Retrying.")
        return MoveToNode.with_parameters(crucible_sentinel_node, unit)


async def crucible_optimization_node(unit: UnitWorkItem, *, deps):
    """OPTIMIZE: Refactor"""
    optimized_code = deps.agent_optimizer(unit.name, unit.code)
    regression = deps.check_regression(optimized_code)

    if regression:
        logging.warning("[CRUCIBLE] Optimization caused regression.")
        return MoveToNode.with_parameters(crucible_optimization_node, unit)

    unit.code = optimized_code
    return FinalResult(result=unit.code)
