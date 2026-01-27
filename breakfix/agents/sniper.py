from pydantic_ai import Agent
from breakfix.models import CodeImplementation, MutationTestResult, BreakfixConfig
from breakfix.sandbox_utils import get_pruner_toolset

# Initialize BreakfixConfig (for now, default values)
_breakfix_config = BreakfixConfig()
_sniper_toolset = get_pruner_toolset(_breakfix_config)

# Define the Sniper Agent
sniper = Agent(
    "openai:gpt-5-mini",
    output_type=MutationTestResult,
    system_prompt=(
        "You are The Sniper, the Attacker of the BreakFix team.\n"
        "Your goal is to sabotage code to expose weak tests through mutation testing.\n"
        "Follow these attack patterns:\n"
        "1. Mutate operators (+ to *, == to !=, etc.)\n"
        "2. Remove method calls and return constants\n"
        "3. Change conditional logic\n"
        "4. Modify loop bounds\n"
        "5. If tests still pass after mutation, the tests are weak\n"
        "You have read/write access to the codebase.\n"
        "Project root is mounted at `/project`.\n"
        "Create mutations and run tests to see if they survive.\n"
        "Return detailed MutationTestResult with surviving mutations and needed improvements."
    ),
    toolsets=[_sniper_toolset],
)
