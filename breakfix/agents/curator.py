from pydantic_ai import Agent
from breakfix.models import RefactoredCode, BreakfixConfig
from breakfix.sandbox_utils import get_curator_toolset, get_mounted_paths

def get_curator(config: BreakfixConfig) -> Agent:
    toolset = get_curator_toolset(config)
    
    code_paths, test_paths, docs_paths = get_mounted_paths(config)

    return Agent(
        "openai:gpt-4.1-mini",
        output_type=RefactoredCode,
        system_prompt=(
            f"You are The Curator, the Cleaner of the BreakFix team.\n"
            "Your goal is to refactor working code and tests for elegance and maintainability.\n"
            "You will receive a list of implementation and test file paths.\n"
            "**CRITICAL INSTRUCTION:**\n"
            "1. You may use `read_file` and `write_file` to modify both implementation and test files.\n"
            "2. If you make any changes, you MUST use the `write_file` tool to update the files on disk BEFORE returning the `RefactoredCode` object.\n"
            "Focus on these improvements:\n"
            "1. Code organization and structure\n"
            "2. Naming conventions and clarity\n"
            "3. Parametrized test suites for better coverage\n"
            "4. Remove duplication (DRY principle)\n"
            "5. Add documentation and comments where helpful\n"
            "6. Optimize imports and dependencies\n"
            f"The mounted code directories are: {code_paths}.\n"
            f"The mounted test directories are: {test_paths}.\n"
            "Refactor code and tests to production quality.\n"
            "Return a RefactoredCode summary of improvements made."
        ),
        toolsets=[toolset],
    )