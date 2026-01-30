import logging
import random
import time
from argparse import Namespace

from breakfix.agents import create_analyst
from breakfix.graph import run_graph, NodeErrored, NodeFailed
from breakfix.nodes import (
    TestCase,
    UnitWorkItem,
    start_project_node,
)


async def run():
    def sim_check(prob):
        # Helper for mock probabilities
        return random.random() < prob

    deps = Namespace(
        input=input,  # Used elsewhere

        # Analyst agent factory (input_fn baked in)
        create_analyst=lambda: create_analyst(model="openai:gpt-5-mini", input_fn=input),

        # Phase 2-4 Agents & Checks
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
        result = await run_graph(start_project_node, deps=deps)
        print(f"\nFinal Artifact: {result}")

    except (NodeErrored, NodeFailed) as e:
        print(f"System Halted: {e}")
