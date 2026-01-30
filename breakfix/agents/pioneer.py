from pydantic_ai import Agent
from breakfix.models import TestSuiteReference, BreakfixConfig
from breakfix.sandbox_utils import get_pioneer_toolset, get_mounted_paths

def get_pioneer(config: BreakfixConfig) -> Agent:
    toolset = get_pioneer_toolset(config)
    
    code_paths, test_paths = get_mounted_paths(config)

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
            