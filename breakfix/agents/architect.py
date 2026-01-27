from pydantic_ai import Agent
from breakfix.models import MicroSpec, BreakfixConfig
from breakfix.sandbox_utils import get_architect_toolset

# Initialize BreakfixConfig (for now, default values)
# In a real scenario, this would be passed from a central orchestration.
_breakfix_config = BreakfixConfig()
_architect_toolset = get_architect_toolset(_breakfix_config)

# Define the Architect Agent
architect = Agent(
    "openai:gpt-5-mini",  # Using a placeholder model. This should be configurable.
    output_type=MicroSpec,
    system_prompt=(
        "You are The Architect, the planner of the BreakFix team.\n"
        "Your goal is to take a user feature request and break it down into a SINGLE, ATOMIC 'Micro-Spec'.\n"
        "The spec must be small enough to be implemented in one go, but complete enough to be testable.\n"
        "Do not write code. Do not write tests. Just define the requirement.\n"
        "You have access to the file system via tools (`list_files` and `read_file`).\n"
        "**CRITICAL:** Be extremely judicious with your use of file system tools to avoid exceeding context limits.\n"
        "The project root is mounted at `/project`.\n"
        "1. Start by listing files in the project root: `list_files(path='/project', pattern='*')`. "
        "   Do NOT use recursive patterns (like `**/*`) initially.\n"
        "2. Only drill down into specific directories if absolutely necessary.\n"
        "3. Only use `read_file` for critical configuration files (e.g., `/project/pyproject.toml`) or small, highly relevant source files.\n"
        "4. Never read large files or list entire directories recursively unless targeted.\n"
        "When providing relevant_files in the MicroSpec, ensure the paths are virtual paths from the sandbox, "
        "e.g., '/project/breakfix/models.py'."
    ),
    toolsets=[_architect_toolset],  # Pass the toolset here
)

# The list_files and read_file tools are automatically provided by _architect_toolset
# and do not need to be explicitly defined here using @architect.tool.
