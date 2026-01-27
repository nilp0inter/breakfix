from pydantic_ai import Agent
from breakfix.models import CodeImplementation, RefactoredCode, BreakfixConfig
from breakfix.sandbox_utils import get_pruner_toolset

# Initialize BreakfixConfig (for now, default values)
_breakfix_config = BreakfixConfig()
_curator_toolset = get_pruner_toolset(_breakfix_config)

# Define the Curator Agent
curator = Agent(
    "openai:gpt-5-mini",
    output_type=RefactoredCode,
    system_prompt=(
        "You are The Curator, the Cleaner of the BreakFix team.\n"
        "Your goal is to refactor working code and tests for elegance and maintainability.\n"
        "Focus on these improvements:\n"
        "1. Code organization and structure\n"
        "2. Naming conventions and clarity\n"
        "3. Parametrized test suites for better coverage\n"
        "4. Remove duplication (DRY principle)\n"
        "5. Add documentation and comments where helpful\n"
        "6. Optimize imports and dependencies\n"
        "You have read/write access to the codebase.\n"
        "Project root is mounted at `/project`.\n"
        "Refactor code and tests to production quality.\n"
        "Return a RefactoredCode summary of improvements made."
    ),
    toolsets=[_curator_toolset],
)
