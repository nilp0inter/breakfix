from pydantic_ai import Agent
from breakfix.models import CoverageReport, BreakfixConfig
from breakfix.sandbox_utils import get_pruner_toolset, get_mounted_paths, run_coverage_analysis

def get_pruner(config: BreakfixConfig) -> Agent:
    toolset = get_pruner_toolset(config)
    
    code_paths, test_paths, docs_paths = get_mounted_paths(config)

    return Agent(
        "openai:gpt-4.1-mini",
        output_type=CoverageReport,
        system_prompt=(
            f"You are The Pruner, the Cynic of the BreakFix team.\n"
            "Your goal is to identify and remove dead code that isn't covered by tests.\n"
            "You will receive a list of implementation and test file paths.\n"
            "**CRITICAL INSTRUCTION:**\n"
            "1. You MUST use the `run_coverage_analysis` tool to analyze the provided files. DO NOT attempt to run `pytest` or coverage commands manually.\n"
            "2. Based on the tool's output, determine if there is dead code.\n"
            f"3. If there is dead code, you may use `read_file` and `write_file` to remove it (only from implementation files, which are in: {code_paths}).\n"
            "4. Return a `CoverageReport` summarizing your findings and actions.\n"
            "Follow YAGNI (You Ain't Gonna Need It) principles:\n"
            "1. Be ruthless - if it's not tested, it doesn't belong\n"
            "2. Remove dead functions, unused imports, unreachable code\n"
            f"The mounted code directories are: {code_paths}.\n"
            f"The mounted test directories are: {test_paths}.\n"
        ),
        toolsets=[toolset],
        tools=[run_coverage_analysis],
    )