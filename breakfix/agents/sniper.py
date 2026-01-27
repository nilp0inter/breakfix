from pydantic_ai import Agent
from breakfix.models import MutationTestResult, BreakfixConfig
from breakfix.sandbox_utils import get_sniper_toolset, get_mounted_paths, run_mutation_testing

def get_sniper(config: BreakfixConfig) -> Agent:
    toolset = get_sniper_toolset(config)
    
    code_paths, test_paths, docs_paths = get_mounted_paths(config)

    return Agent(
        "openai:gpt-4.1-mini",
        output_type=MutationTestResult,
        system_prompt=(
            f"You are The Sniper, the Attacker of the BreakFix team.\n"
            "Your goal is to sabotage code to expose weak tests through mutation testing.\n"
            "You will receive a list of implementation and test file paths.\n"
            "**CRITICAL INSTRUCTION:**\n"
            "1. You MUST use the `run_mutation_testing` tool to perform the analysis. This tool runs externally and handles all file modifications safely.\n"
            "2. **DO NOT** attempt to modify any files (tests or code) yourself. You are strictly forbidden from using `write_file`.\n"
            "3. Use the output from the tool to report on surviving mutations and weaknesses.\n"
            "Follow these attack patterns (simulated by the tool):\n"
            "1. Mutate operators (+ to *, == to !=, etc.)\n"
            "2. Remove method calls and return constants\n"
            "3. Change conditional logic\n"
            "4. Modify loop bounds\n"
            f"The mounted code directories are: {code_paths}.\n"
            f"The mounted test directories are: {test_paths}.\n"
            "Return detailed MutationTestResult with surviving mutations and needed improvements."
        ),
        toolsets=[toolset],
        tools=[run_mutation_testing],
    )