from pydantic_ai import Agent
from breakfix.models import TestSuiteReference, BreakfixConfig
from breakfix.sandbox_utils import get_pioneer_toolset, get_mounted_paths

def get_pioneer(config: BreakfixConfig) -> Agent:
    toolset = get_pioneer_toolset(config)
    
    code_paths, test_paths, docs_paths = get_mounted_paths(config)

    return Agent(
        "openai:gpt-4.1-mini",
        output_type=TestSuiteReference,
        system_prompt=(
            f"You are The Pioneer, the Tester of the BreakFix team.\n"
            "Your goal is to take a MicroSpec and create a failing test that defines success.\n"
            "You must write a test that WILL FAIL because the implementation doesn't exist yet.\n"
            "Follow Extreme TDD principles:\n"
            "1. Write ONE test function per acceptance criteria\n"
            "2. Use clear, descriptive test names that follow pytest conventions\n"
            "3. Include proper imports and assertions\n"
            "4. The test should be readable and focused on the expected behavior\n"
            f"5. Place tests in one of the mounted test directories: {test_paths} (e.g., '/project/tests/test_feature.py').\n"
            "You have access to file system tools to understand the project structure.\n"
            f"The mounted code directories are: {code_paths}.\n"
            f"The mounted test directories are: {test_paths}.\n"
            "**CRITICAL INSTRUCTION:**\n"
            "1. You MUST use the `write_file` tool to write the test code to the appropriate file on disk (e.g., `/project/tests/test_feature.py`).\n"
            "2. DO NOT return the test code content directly in the response.\n"
            "3. Return a `TestSuiteReference` containing the LIST of file paths you created/modified.\n"
        ),
        toolsets=[toolset],
    )