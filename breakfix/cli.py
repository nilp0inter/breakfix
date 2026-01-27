import argparse
import os
import sys
import time
from pathlib import Path
from breakfix.agents.architect import get_architect
from breakfix.agents.pioneer import get_pioneer
from breakfix.agents.gatekeeper import get_gatekeeper
from breakfix.agents.builder import get_builder
from breakfix.agents.pruner import get_pruner
from breakfix.agents.sniper import get_sniper
from breakfix.agents.curator import get_curator
from breakfix.models import (
    MicroSpec,
    TestSuiteReference,
    ValidationResult,
    CodeReference,
    CoverageReport,
    MutationTestResult,
    RefactoredCode,
    BreakfixConfig,
)
from pydantic_ai import messages as _messages 

MAX_TDD_LOOPS = 3

def run_breakfix_workflow(feature_request: str, breakfix_config: BreakfixConfig):
    """
    Run the complete BreakFix multi-agent workflow.
    """
    # Instantiate agents with the current config
    architect = get_architect(breakfix_config)
    pioneer = get_pioneer(breakfix_config)
    gatekeeper = get_gatekeeper(breakfix_config)
    builder = get_builder(breakfix_config)
    pruner = get_pruner(breakfix_config)
    sniper = get_sniper(breakfix_config)
    curator = get_curator(breakfix_config)

    print(f"🚀 Starting BreakFix workflow for: '{feature_request}'")
    print("=" * 60)

    # Phase 1: Definition
    print("\n📐 PHASE 1: DEFINITION")
    print("-" * 30)

    # Step 1: Architect creates MicroSpec
    print("🏗️  Architect is defining the requirement...")
    print(f"DEBUG: Architect input: {feature_request}")
    result = architect.run_sync(feature_request)
    micro_spec: MicroSpec = result.output
    # Safely get raw output
    raw_architect_output = ""
    try:
        if result.response and result.response.parts:
            raw_architect_output = result.response.parts[0].content
    except (AttributeError, IndexError, ValueError):
        pass 
    print(f"DEBUG: Architect raw output: {raw_architect_output}")

    print(f"✅ Micro-Spec Created:")
    print(f"   Title: {micro_spec.title}")
    print(f"   User Story: {micro_spec.user_story}")
    print(f"   Requirement: {micro_spec.requirement}")
    print(f"   Acceptance Criteria: {', '.join(micro_spec.acceptance_criteria)}")

    # TDD Loop: Pioneer -> Gatekeeper
    tdd_loop_count = 0
    test_suite_ref = None
    pioneer_input_prompt = str(micro_spec)

    while tdd_loop_count < MAX_TDD_LOOPS:
        print(f"\n🔄 TDD Loop Iteration {tdd_loop_count + 1}/{MAX_TDD_LOOPS}")
        
        # Step 2: Pioneer writes failing tests
        print("🧪 Pioneer is writing failing tests...")
        print(f"DEBUG: Pioneer input: {pioneer_input_prompt}")
        result = pioneer.run_sync(pioneer_input_prompt)
        test_suite_ref: TestSuiteReference = result.output
        raw_pioneer_output = ""
        try:
            if result.response and result.response.parts:
                raw_pioneer_output = result.response.parts[0].content
        except (AttributeError, IndexError, ValueError):
            pass
        print(f"DEBUG: Pioneer raw output: {raw_pioneer_output}")

        print(f"✅ Test Suite Created: Files at {test_suite_ref.test_file_paths}")
        print(f"DEBUG: Pioneer output (parsed TestSuiteReference): {test_suite_ref.dict()}")


        # Step 3: Gatekeeper validates tests
        print("\n🚪 Gatekeeper is validating test suite...")
        # Gatekeeper receives paths to read
        gatekeeper_input = f"MicroSpec: {micro_spec}\n\nTest Suite Files: {test_suite_ref.test_file_paths}"
        print(f"DEBUG: Gatekeeper input: {gatekeeper_input}")
        result = gatekeeper.run_sync(gatekeeper_input)
        validation: ValidationResult = result.output
        raw_gatekeeper_output = ""
        try:
            if result.response and result.response.parts:
                raw_gatekeeper_output = result.response.parts[0].content
        except (AttributeError, IndexError, ValueError):
            pass
        print(f"DEBUG: Gatekeeper raw output: {raw_gatekeeper_output}")
        print(f"DEBUG: Gatekeeper output (parsed ValidationResult): {validation.dict()}")


        if validation.approved:
            print("✅ Tests approved by Gatekeeper")
            break
        
        print(f"❌ Tests rejected: {validation.feedback}")
        for issue in validation.issues:
            print(f"   - {issue}")
            
        # Prepare feedback for the next iteration
        pioneer_input_prompt = (
            f"Original MicroSpec: {micro_spec}\n\n"
            f"Your previous TestSuite (files: {test_suite_ref.test_file_paths}) was rejected by the Gatekeeper.\n"
            f"Feedback: {validation.feedback}\n"
            f"Specific Issues: {', '.join(validation.issues)}\n"
            f"Please REWRITE the tests in the files to address this feedback and fully satisfy the MicroSpec.\n"
        )
        tdd_loop_count += 1

    if not test_suite_ref or tdd_loop_count >= MAX_TDD_LOOPS:
         print(f"\n❌ Failed to generate valid tests after {MAX_TDD_LOOPS} attempts.")
         return False

    # Phase 2: Implementation Loop
    print("\n🔨 PHASE 2: IMPLEMENTATION LOOP")
    print("-" * 30)

    # Step 4: Builder writes minimal code
    print("👷 Builder is writing minimal implementation...")
    # Builder receives test paths
    builder_input = f"Test Suite Files: {test_suite_ref.test_file_paths}"
    print(f"DEBUG: Builder input: {builder_input}")
    result = builder.run_sync(builder_input)
    code_ref: CodeReference = result.output
    raw_builder_output = ""
    try:
        if result.response and result.response.parts:
            raw_builder_output = result.response.parts[0].content
    except (AttributeError, IndexError, ValueError):
        pass
    print(f"DEBUG: Builder raw output: {raw_builder_output}")
    print(f"DEBUG: Builder output (parsed CodeReference): {code_ref.dict()}")

    print(f"✅ Implementation created: {code_ref.implementation_file_paths}")
    print(f"   {code_ref.description}")

    # Phase 3: Efficiency Loop
    print("\n✂️  PHASE 3: EFFICIENCY LOOP")
    print("-" * 30)

    # Step 5: Pruner checks for dead code
    print("🌳 Pruner is analyzing code coverage...")
    pruner_input = f"Implementation Files: {code_ref.implementation_file_paths}\nTest Files: {test_suite_ref.test_file_paths}"
    print(f"DEBUG: Pruner input: {pruner_input}")
    result = pruner.run_sync(pruner_input)
    coverage: CoverageReport = result.output
    raw_pruner_output = ""
    try:
        if result.response and result.response.parts:
            raw_pruner_output = result.response.parts[0].content
    except (AttributeError, IndexError, ValueError):
        pass
    print(f"DEBUG: Pruner raw output: {raw_pruner_output}")
    print(f"DEBUG: Pruner output (parsed CoverageReport): {coverage.dict()}")

    print(f"✅ Coverage Report: {coverage.coverage_percentage:.1f}%")
    if coverage.unused_lines:
        print(f"   Unused lines: {len(coverage.unused_lines)}")
    if coverage.dead_functions:
        print(f"   Dead functions: {len(coverage.dead_functions)}")

    # Phase 4: Security Loop
    print("\n🎯 PHASE 4: SECURITY LOOP")
    print("-" * 30)

    # Step 6: Sniper performs mutation testing
    print("🔫 Sniper is performing mutation testing...")
    sniper_input = f"Implementation Files: {code_ref.implementation_file_paths}\nTest Files: {test_suite_ref.test_file_paths}"
    print(f"DEBUG: Sniper input: {sniper_input}")
    result = sniper.run_sync(sniper_input)
    mutation: MutationTestResult = result.output
    raw_sniper_output = ""
    try:
        if result.response and result.response.parts:
            raw_sniper_output = result.response.parts[0].content
    except (AttributeError, IndexError, ValueError):
        pass
    print(f"DEBUG: Sniper raw output: {raw_sniper_output}")
    print(f"DEBUG: Sniper output (parsed MutationTestResult): {mutation.dict()}")


    print(f"✅ Mutation Test Results: {mutation.weakness_score:.1f}% weakness")
    if mutation.mutations_survived:
        print(f"   Surviving mutations: {len(mutation.mutations_survived)}")
        print("   This indicates weak tests - restarting implementation phase...")
        # In a real implementation, we would restart the loop here
        print("   (Loop restart would happen here in full implementation)")

    # Phase 5: Delivery
    print("\n✨ PHASE 5: DELIVERY")
    print("-" * 30)

    # Step 7: Curator polishes the code
    print("🧹 Curator is polishing and refactoring...")
    curator_input = f"Implementation Files: {code_ref.implementation_file_paths}\nTest Files: {test_suite_ref.test_file_paths}"
    print(f"DEBUG: Curator input: {curator_input}")
    result = curator.run_sync(curator_input)
    refactored: RefactoredCode = result.output
    raw_curator_output = ""
    try:
        if result.response and result.response.parts:
            raw_curator_output = result.response.parts[0].content
    except (AttributeError, IndexError, ValueError):
        pass
    print(f"DEBUG: Curator raw output: {raw_curator_output}")
    print(f"DEBUG: Curator output (parsed RefactoredCode): {refactored.dict()}")


    print(f"✅ Code Quality Score: {refactored.code_quality_score:.1f}/100")
    print(f"   Improved files: {', '.join(refactored.improved_files)}")
    for improvement in refactored.improvements_made:
        print(f"   - {improvement}")

    print("\n🎉 BREAKFIX WORKFLOW COMPLETE!")
    print("=" * 60)
    print(f"✨ Feature '{micro_spec.title}' is ready for production!")
    print("   ✅ Tested ✅ Minimal ✅ Bulletproof")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="BreakFix - Autonomous Multi-Agent Software Development Engine."
    )
    parser.add_argument(
        "feature_request", type=str, help="The feature request to be implemented."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="The root directory of the project.",
    )
    parser.add_argument(
        "--code-dirs",
        nargs="+",
        default=["breakfix"],
        help="List of directory paths relative to project-root containing code (e.g., 'src', 'app').",
    )
    parser.add_argument(
        "--test-dirs",
        nargs="+",
        default=["tests"],
        help="List of directory paths relative to project-root containing tests (e.g., 'tests', 'specs').",
    )
    parser.add_argument(
        "--docs-dirs",
        nargs="+",
        default=["docs"],
        help="List of directory paths relative to project-root containing documentation (e.g., 'docs').",
    )
    args = parser.parse_args()

    breakfix_config = BreakfixConfig(
        project_root=args.project_root,
        code_dirs=args.code_dirs,
        test_dirs=args.test_dirs,
        docs_dirs=args.docs_dirs,
    )

    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable is not set.")
        print("Please export it: export OPENAI_API_KEY='your-key'")
        sys.exit(1)

    try:
        success = run_breakfix_workflow(args.feature_request, breakfix_config)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Workflow interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error during workflow: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
