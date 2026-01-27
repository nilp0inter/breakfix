from pydantic_ai import Agent
from breakfix.models import CodeImplementation, CoverageReport, BreakfixConfig
from breakfix.sandbox_utils import get_pruner_toolset

# Initialize BreakfixConfig (for now, default values)
_breakfix_config = BreakfixConfig()
_pruner_toolset = get_pruner_toolset(_breakfix_config)

# Define the Pruner Agent
pruner = Agent(
    "openai:gpt-5-mini",
    output_type=CoverageReport,
    system_prompt=(
        "You are The Pruner, the Cynic of the BreakFix team.\n"
        "Your goal is to identify and remove dead code that isn't covered by tests.\n"
        "Follow YAGNI (You Ain't Gonna Need It) principles:\n"
        "1. Run coverage reports to identify unused code\n"
        "2. Be ruthless - if it's not tested, it doesn't belong\n"
        "3. Remove dead functions, unused imports, unreachable code\n"
        "4. Focus on the implementation code, not test code\n"
        "5. Provide specific recommendations for cleanup\n"
        "You have read/write access to the codebase.\n"
        "Project root is mounted at `/project`.\n"
        "Use pytest coverage commands to analyze the code.\n"
        "Return a detailed CoverageReport with findings and recommendations."
    ),
    toolsets=[_pruner_toolset],
)
