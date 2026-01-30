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

    return MoveToNode.with_parameters(phase_prototyping_node, state)


async def phase_prototyping_node(state: ProjectState, *, deps):
    logging.info("[OUTER] Phase 2: Prototyping")
    draft_code = deps.agent_prototyper(state.spec)
    e2e_pass, msg = deps.check_e2e_harness(draft_code)

    if not e2e_pass:
        logging.warning(f"E2E Failed: {msg}")
        return MoveToNode.with_parameters(phase_prototyping_node, state)

    state.prototype_code = draft_code
    return MoveToNode.with_parameters(phase_refinement_node, state)


async def phase_refinement_node(state: ProjectState, *, deps):
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
