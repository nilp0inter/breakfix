from functools import partial
from dataclasses import dataclass, field
from typing import Callable, Any, List
from argparse import Namespace
import random
import logging
import time

# --- USER'S GRAPH LIBRARY (UNCHANGED) ---
@dataclass
class MoveToNode:
    fn: Callable
    @classmethod
    def with_parameters(cls, fn, *args, **kwargs):
        return cls(partial(fn, *args, **kwargs))

@dataclass
class NodeError:
    error: str

@dataclass
class FinalResult:
    result: Any

class NodeErrored(Exception):
    pass

class NodeFailed(Exception):
    pass

def run_graph(start_node: Callable, *args, deps, **kwargs) -> Any:
    try:
        logging.info(f"--- Starting new graph execution context [{start_node.__name__}] ---")
        node_result = start_node(*args, **kwargs, deps=deps)
        logging.info(f"Initial node executed. Result: {node_result}")
    except Exception as e:
        raise NodeFailed("Initial node failed") from e
    else:
        while node_result:
            match node_result:
                case MoveToNode(fn=fn):
                    logging.info(f"Moving to next node: {fn.func.__name__ if isinstance(fn, partial) else fn.__name__}")
                    try:
                        node_result = fn(deps=deps)
                    except Exception as e:
                        raise NodeFailed("Node execution failed") from e
                case FinalResult(result=res):
                    logging.info("Final result reached for current graph context.")
                    return res
                case NodeError(error=err):
                    logging.error(f"Node returned an error: {err}")
                    raise NodeErrored(err)

# --- DATA STRUCTURES ---

@dataclass
class TestCase:
    id: int
    description: str

@dataclass
class UnitWorkItem:
    name: str
    tests: List[TestCase]
    code: str = "" # Stores the evolving code for this unit

@dataclass
class ProjectState:
    user_idea: str
    spec: str = ""
    prototype_code: str = ""
    refined_arch: str = ""
    unit_queue: List[UnitWorkItem] = field(default_factory=list)
    finished_units: List[str] = field(default_factory=list)

# ==============================================================================
# OUTER GRAPH: PROJECT SCOPE
# (Spec -> Proto -> Refine -> Distill -> Unit Orchestrator)
# ==============================================================================

def start_project_node(deps):
    user_idea = deps.input("Enter your software idea: ")
    state = ProjectState(user_idea=user_idea)
    return MoveToNode.with_parameters(phase_specification_node, state)

def phase_specification_node(state: ProjectState, *, deps):
    logging.info("[OUTER] Phase 1: Specification")
    draft_spec = deps.agent_analyst(state.user_idea)
    is_valid, msg = deps.check_spec_consistency(draft_spec)
    
    if not is_valid:
        logging.warning(f"Spec Check Failed: {msg}")
        return MoveToNode.with_parameters(phase_specification_node, state)
    
    state.spec = draft_spec
    return MoveToNode.with_parameters(phase_prototyping_node, state)

def phase_prototyping_node(state: ProjectState, *, deps):
    logging.info("[OUTER] Phase 2: Prototyping")
    draft_code = deps.agent_prototyper(state.spec)
    e2e_pass, msg = deps.check_e2e_harness(draft_code)
    
    if not e2e_pass:
        logging.warning(f"E2E Failed: {msg}")
        return MoveToNode.with_parameters(phase_prototyping_node, state)
    
    state.prototype_code = draft_code
    return MoveToNode.with_parameters(phase_refinement_node, state)

def phase_refinement_node(state: ProjectState, *, deps):
    logging.info("[OUTER] Phase 3: Refinement")
    refined_code = deps.agent_architect(state.prototype_code)
    is_clean, msg = deps.check_architectural_taint(refined_code)
    
    if not is_clean:
        logging.warning(f"Arch Violation: {msg}")
        return MoveToNode.with_parameters(phase_refinement_node, state)
    
    state.refined_arch = refined_code
    return MoveToNode.with_parameters(phase_distillation_node, state)

def phase_distillation_node(state: ProjectState, *, deps):
    logging.info("[OUTER] Phase 4: Distillation")
    units = deps.process_dependency_graph(state.refined_arch)
    state.unit_queue = units
    return MoveToNode.with_parameters(unit_orchestrator_node, state)

def unit_orchestrator_node(state: ProjectState, *, deps):
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
        finalized_unit_code = run_graph(
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

def inner_unit_start_node(unit: UnitWorkItem, *, deps):
    """Entry point for the Inner Graph"""
    return MoveToNode.with_parameters(ratchet_iterator_node, unit)

def ratchet_iterator_node(unit: UnitWorkItem, *, deps):
    """Iterates through tests for the unit"""
    if not unit.tests:
        logging.info(f"[INNER] All tests passed for {unit.name}. Entering Crucible.")
        return MoveToNode.with_parameters(crucible_mutation_node, unit)
    
    current_test = unit.tests.pop(0)
    logging.info(f"[ATOMIC] Ratchet Cycle for Test: {current_test.description}")
    
    # Enter the Ratchet Cycle for this specific test
    return MoveToNode.with_parameters(ratchet_red_node, unit, current_test)

def ratchet_red_node(unit: UnitWorkItem, test: TestCase, *, deps):
    """RED: Write Failing Test"""
    # In real logic, we'd append to unit.code or test suite files
    test_code = deps.agent_tester(unit.name, test.description)
    valid_red = deps.check_ratchet_red_state(test_code)
    
    if not valid_red:
        logging.warning("[ATOMIC] Red Check Failed. Retrying.")
        return MoveToNode.with_parameters(ratchet_red_node, unit, test)
        
    return MoveToNode.with_parameters(ratchet_green_node, unit, test)

def ratchet_green_node(unit: UnitWorkItem, test: TestCase, *, deps):
    """GREEN: Write Passing Code"""
    impl_code = deps.agent_developer(unit.name, test.description)
    valid_green = deps.check_ratchet_green_coverage(impl_code)
    
    if not valid_green:
        logging.warning("[ATOMIC] Green/Coverage Check Failed. Retrying.")
        return MoveToNode.with_parameters(ratchet_green_node, unit, test)
    
    # Commit code to unit state
    unit.code += f"\n# Impl for {test.description}"
    return MoveToNode.with_parameters(ratchet_iterator_node, unit)

def crucible_mutation_node(unit: UnitWorkItem, *, deps):
    """CRUCIBLE: Mutation Testing"""
    score = deps.process_mutation_testing(unit.name)
    if score < 1.0:
        logging.warning(f"[CRUCIBLE] Mutation Score {score}. Deploying Sentinel.")
        return MoveToNode.with_parameters(crucible_sentinel_node, unit)
    
    return MoveToNode.with_parameters(crucible_optimization_node, unit)

def crucible_sentinel_node(unit: UnitWorkItem, *, deps):
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

def crucible_optimization_node(unit: UnitWorkItem, *, deps):
    """OPTIMIZE: Refactor"""
    optimized_code = deps.agent_optimizer(unit.name, unit.code)
    regression = deps.check_regression(optimized_code)
    
    if regression:
        logging.warning("[CRUCIBLE] Optimization caused regression.")
        return MoveToNode.with_parameters(crucible_optimization_node, unit)
    
    unit.code = optimized_code
    return FinalResult(result=unit.code)


# ==============================================================================
# EXECUTION HARNESS
# ==============================================================================

def run_simulation():
    def sim_check(prob):
        # Helper for mock probabilities
        time.sleep(0.01)
        return random.random() < prob

    deps = Namespace(
        input=lambda x: "E-Commerce Cart System",
        
        # Phase 1-4 Agents & Checks
        agent_analyst=lambda x: "Spec v1",
        check_spec_consistency=lambda x: (True, "") if sim_check(0.9) else (False, "Bad JSON"),
        agent_prototyper=lambda x: "def proto(): pass",
        check_e2e_harness=lambda x: (True, "") if sim_check(0.7) else (False, "404 Error"),
        agent_architect=lambda x: "src/core",
        check_architectural_taint=lambda x: (True, "") if sim_check(0.8) else (False, "import sys"),
        process_dependency_graph=lambda x: [
            UnitWorkItem("Cart", [TestCase(1, "Add Item"), TestCase(2, "Remove Item")]),
            UnitWorkItem("TaxCalc", [TestCase(3, "VAT Calc")])
        ],
        
        # Phase 5 Agents & Checks
        agent_tester=lambda u, t: "test_fn()",
        check_ratchet_red_state=lambda x: sim_check(0.8),
        agent_developer=lambda u, t: "return True",
        check_ratchet_green_coverage=lambda x: sim_check(0.7),
        
        # Phase 6 Agents & Checks
        process_mutation_testing=lambda u: 1.0 if sim_check(0.6) else 0.5,
        agent_sentinel=lambda u: "test_killer()",
        check_mutant_killed=lambda t: sim_check(0.8),
        agent_optimizer=lambda u, c: "optimized_code()",
        check_regression=lambda c: not sim_check(0.8)
    )

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    try:
        # Start the Outer Graph
        result = run_graph(start_project_node, deps=deps)
        print(f"\nFinal Artifact: {result}")
        
    except (NodeErrored, NodeFailed) as e:
        print(f"System Halted: {e}")

if __name__ == '__main__':
    run_simulation()
