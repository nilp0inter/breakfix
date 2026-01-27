from pydantic_ai import Agent
from breakfix.models import CodeReference, BreakfixConfig
from breakfix.sandbox_utils import get_builder_toolset, get_mounted_paths

def get_builder(config: BreakfixConfig) -> Agent:
    toolset = get_builder_toolset(config)
    
    code_paths, test_paths, docs_paths = get_mounted_paths(config)

    return Agent(
        "openai:gpt-4.1-mini",
        output_type=CodeReference,
        system_prompt=(
            f"You are The Builder, the Coder of the BreakFix team.\n"
            "Your goal is to write the MINIMAL code needed to make the failing tests pass.\n"
            "You will receive a list of test file paths.\n"
            "**CRITICAL INSTRUCTION:**\n"
            "1. Use `read_file` to read the test files to understand the requirements.\n"
            f"2. Write the implementation code into one of these code directories: {code_paths} (e.g., `/project/src/module.py`).\n"
            "3. Use `write_file` to save your implementation to a file.\n"
            "4. Return a `CodeReference` containing the LIST of implementation file paths you created.\n"
            "Follow these principles:\n"
            "1. LAZINESS - Write only what's necessary to turn red to green\n"
            "2. MINIMALISM - No extra features, no 'nice-to-haves', just pass the tests\n"
            "3. SIMPLICITY - Use the simplest possible implementation\n"
            "4. FOCUS - Only implement what the tests actually check for\n"
            "You have read/write access to the codebase.\n"
            f"The mounted code directories are: {code_paths}.\n"
            f"The mounted test directories are: {test_paths}.\n"
        ),
        toolsets=[toolset],
    )
