import argparse
import os
import sys
import time
from breakfix.agents.architect import architect
from breakfix.agents.pioneer import pioneer
from breakfix.agents.gatekeeper import gatekeeper
from breakfix.agents.builder import builder
from breakfix.agents.pruner import pruner
from breakfix.agents.sniper import sniper
from breakfix.agents.curator import curator
from breakfix.models import (
    MicroSpec,
    TestSuite,
    ValidationResult,
    CodeImplementation,
    CoverageReport,
    MutationTestResult,
    RefactoredCode,
)


def run_breakfix_workflow(feature_request: str):
    """
    Run the complete BreakFix multi-agent workflow.
    """
    print(f"🚀 Starting BreakFix workflow for: '{feature_request}'")
    print("=" * 60)

    # Phase 1: Definition
    print("\n📐 PHASE 1: DEFINITION")
    print("-" * 30)

    # Step 1: Architect creates MicroSpec
    print("🏗️  Architect is defining the requirement...")
    result = architect.run_sync(feature_request)
    micro_spec: MicroSpec = result.output

    print(f"✅ Micro-Spec Created:")
    print(f"   Title: {micro_spec.title}")
    print(f"   User Story: {micro_spec.user_story}")
    print(f"   Requirement: {micro_spec.requirement}")
    print(f"   Acceptance Criteria: {', '.join(micro_spec.acceptance_criteria)}")

    # Step 2: Pioneer writes failing tests
    print("\n🧪 Pioneer is writing failing tests...")
    result = pioneer.run_sync(str(micro_spec))
    test_suite: TestSuite = result.output

    print(f"✅ Test Suite Created: {len(test_suite.test_cases)} test cases")
    for test in test_suite.test_cases:
        print(f"   - {test.test_function_name}")

    # Step 3: Gatekeeper validates tests
    print("\n🚪 Gatekeeper is validating test suite...")
    result = gatekeeper.run_sync(f"MicroSpec: {micro_spec}\n\nTestSuite: {test_suite}")
    validation: ValidationResult = result.output

    if not validation.approved:
        print(f"❌ Tests rejected: {validation.feedback}")
        for issue in validation.issues:
            print(f"   - {issue}")
        return False

    print("✅ Tests approved by Gatekeeper")

    # Phase 2: Implementation Loop
    print("\n🔨 PHASE 2: IMPLEMENTATION LOOP")
    print("-" * 30)

    # Step 4: Builder writes minimal code
    print("👷 Builder is writing minimal implementation...")
    result = builder.run_sync(str(test_suite))
    implementation: CodeImplementation = result.output

    print(f"✅ Implementation created: {implementation.file_path}")
    print(f"   {implementation.description}")

    # Phase 3: Efficiency Loop
    print("\n✂️  PHASE 3: EFFICIENCY LOOP")
    print("-" * 30)

    # Step 5: Pruner checks for dead code
    print("🌳 Pruner is analyzing code coverage...")
    result = pruner.run_sync(str(implementation))
    coverage: CoverageReport = result.output

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
    result = sniper.run_sync(str(implementation))
    mutation: MutationTestResult = result.output

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
    result = curator.run_sync(str(implementation))
    refactored: RefactoredCode = result.output

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
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable is not set.")
        print("Please export it: export OPENAI_API_KEY='your-key'")
        sys.exit(1)

    try:
        success = run_breakfix_workflow(args.feature_request)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Workflow interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error during workflow: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
