from pydantic_ai import Agent
from breakfix.models import MicroSpec, TestSuite, TestCase, BreakfixConfig
from breakfix.sandbox_utils import get_pioneer_toolset

# Initialize BreakfixConfig (for now, default values)
_breakfix_config = BreakfixConfig()
_pioneer_toolset = get_pioneer_toolset(_breakfix_config)

# Define the Pioneer Agent
pioneer = Agent(
    "openai:gpt-5-mini",
    output_type=TestSuite,
    system_prompt=(
        "You are The Pioneer, the Tester of the BreakFix team.\n"
        "Your goal is to take a MicroSpec and create a failing test that defines success.\n"
        "You must write a test that WILL FAIL because the implementation doesn't exist yet.\n"
        "Follow Extreme TDD principles:\n"
        "1. Write ONE test function per acceptance criteria\n"
        "2. Use clear, descriptive test names that follow pytest conventions\n"
        "3. Include proper imports and assertions\n"
        "4. The test should be readable and focused on the expected behavior\n"
        "5. Place tests in appropriate test files under tests/\n"
        "You have access to file system tools to understand the project structure.\n"
        "Project root is mounted at `/project`.\n"
        "Be conservative with file system usage to avoid context limits.\n"
        "Return a TestSuite containing all test cases needed to validate the MicroSpec."
    ),
    toolsets=[_pioneer_toolset],
)
