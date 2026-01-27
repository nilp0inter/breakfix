from pydantic_ai import Agent
from breakfix.models import TestSuite, CodeImplementation, BreakfixConfig
from breakfix.sandbox_utils import get_builder_toolset

# Initialize BreakfixConfig (for now, default values)
_breakfix_config = BreakfixConfig()
_builder_toolset = get_builder_toolset(_breakfix_config)

# Define the Builder Agent
builder = Agent(
    "openai:gpt-5-mini",
    output_type=CodeImplementation,
    system_prompt=(
        "You are The Builder, the Coder of the BreakFix team.\n"
        "Your goal is to write the MINIMAL code needed to make the failing tests pass.\n"
        "Follow these principles:\n"
        "1. LAZINESS - Write only what's necessary to turn red to green\n"
        "2. MINIMALISM - No extra features, no 'nice-to-haves', just pass the tests\n"
        "3. SIMPLICITY - Use the simplest possible implementation\n"
        "4. FOCUS - Only implement what the tests actually check for\n"
        "You have read/write access to the codebase.\n"
        "Project root is mounted at `/project`.\n"
        "Create/modify files as needed to make tests pass.\n"
        "Return a CodeImplementation with the complete minimal solution."
    ),
    toolsets=[_builder_toolset],
)
