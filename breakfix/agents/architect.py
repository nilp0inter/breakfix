from pydantic_ai import Agent
from breakfix.models import MicroSpec, BreakfixConfig
from breakfix.sandbox_utils import get_architect_toolset

# Initialize BreakfixConfig (for now, default values)
# In a real scenario, this would be passed from a central orchestration.
_breakfix_config = BreakfixConfig()
_architect_toolset = get_architect_toolset(_breakfix_config)

# Define the Architect Agent
architect = Agent(
    'openai:gpt-4o',  # Using a placeholder model. This should be configurable.
    output_type=MicroSpec,
    system_prompt=(
        "You are The Architect, the planner of the BreakFix team.\n"
        "Your goal is to take a user feature request and break it down into a SINGLE, ATOMIC 'Micro-Spec'.\n"
        "The spec must be small enough to be implemented in one go, but complete enough to be testable.\n"
        "Do not write code. Do not write tests. Just define the requirement.\n"
        "You have access to the file system via tools (`list_files` and `read_file`).\n"
        "**CRITICAL:** Be extremely judicious with your use of file system tools to avoid exceeding context limits.\n"
        "First, use `list_files(path='/')` to get an overview of the available top-level directories and files.\n"
        "Then, use `list_files` with specific paths like `/app` or `/tests` only if absolutely necessary to understand the structure for this specific Micro-Spec.\n"
        "Only use `read_file` for critical configuration files like `/pyproject.toml`, `/README.md`, or `/GEMINI.md`, or very specific small files within `/app` or `/tests` if their content is directly relevant to defining the Micro-Spec.\n"
        "Never read large files or list entire directories recursively. Prioritize brevity and relevance in your file system interactions.\n"
        "When providing relevant_files in the MicroSpec, ensure the paths are virtual paths from the sandbox, "
        "e.g., '/app/breakfix/models.py' if the file is within the '/app' mount."
    ),
    toolsets=[_architect_toolset] # Pass the toolset here
)

# The list_files and read_file tools are automatically provided by _architect_toolset
# and do not need to be explicitly defined here using @architect.tool.
