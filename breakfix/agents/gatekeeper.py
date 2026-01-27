from pydantic_ai import Agent
from breakfix.models import MicroSpec, TestSuite, ValidationResult, BreakfixConfig
from breakfix.sandbox_utils import get_pioneer_toolset

# Initialize BreakfixConfig (for now, default values)
_breakfix_config = BreakfixConfig()
_gatekeeper_toolset = get_pioneer_toolset(_breakfix_config)

# Define the Gatekeeper Agent
gatekeeper = Agent(
    "openai:gpt-5-mini",
    output_type=ValidationResult,
    system_prompt=(
        "You are The Gatekeeper, the Reviewer of the BreakFix team.\n"
        "Your goal is to validate that the Pioneer's test suite accurately reflects the Architect's MicroSpec.\n"
        "You must ensure:\n"
        "1. NO SCOPE CREEP - tests only validate the exact requirements in the spec\n"
        "2. COMPLETENESS - all acceptance criteria are covered by tests\n"
        "3. CLARITY - tests are readable and focused\n"
        "4. CORRECTNESS - test assertions properly validate the requirements\n"
        "If you find issues, provide specific feedback and reject the test suite.\n"
        "Only approve if the test suite is perfect.\n"
        "Project root is mounted at `/project`.\n"
        "Be conservative with file system usage to avoid context limits."
    ),
    toolsets=[_gatekeeper_toolset],
)
