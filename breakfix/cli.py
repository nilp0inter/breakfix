import argparse
import os
import sys
from breakfix.agents.architect import architect
from breakfix.models import MicroSpec

def main():
    parser = argparse.ArgumentParser(description="BreakFix - Autonomous Multi-Agent Software Development Engine.")
    parser.add_argument("feature_request", type=str, help="The feature request to be implemented.")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable is not set.")
        print("Please export it: export OPENAI_API_KEY='your-key'")
        sys.exit(1)

    print(f"Received feature request: '{args.feature_request}'")

    # Call the Architect agent
    print("\nArchitect is processing the request...")
    try:
        # The Architect will use its tools (list_files, read_file) to understand the project context
        # and then generate the MicroSpec.
        result = architect.run_sync(args.feature_request)
        micro_spec: MicroSpec = result.data
        
        print("\nArchitect generated Micro-Spec:")
        print(f"Title: {micro_spec.title}")
        print(f"User Story: {micro_spec.user_story}")
        print(f"Requirement: {micro_spec.requirement}")
        print(f"Acceptance Criteria: {', '.join(micro_spec.acceptance_criteria)}")
        print(f"Relevant Files: {', '.join(micro_spec.relevant_files)}")
    except Exception as e:
        print(f"Error while running Architect: {e}")
        # Print available attributes to debug if needed
        # print(dir(result) if 'result' in locals() else "Result not available")

if __name__ == "__main__":
    main()