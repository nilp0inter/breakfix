from pydantic_ai import Agent
from breakfix.models import MicroSpec, BreakfixConfig
from breakfix.sandbox_utils import get_architect_toolset, get_mounted_paths

def get_architect(config: BreakfixConfig) -> Agent:
    toolset = get_architect_toolset(config)
    
    code_paths, test_paths = get_mounted_paths(config)
    
    return Agent(
        "openai:gpt-4.1-mini",
        output_type=MicroSpec,
        system_prompt=(
            f"You are The Architect, the planner of the BreakFix team.\n"
            "Your goal is to take a user feature request and break it down into a SINGLE, ATOMIC 'Micro-Spec'.\n"
            "The spec must be small enough to be implemented in one go, but complete enough to be testable.\n"
            "Do not write code. Do not write tests. Just define the requirement.\n"
            "You have access to the file system via tools (`list_files` and `read_file`).\n"
            "**CRITICAL:** Be extremely judicious with your use of file system tools to avoid exceeding context limits.\n"
            f"The mounted code directories are: {code_paths}.\n"
            f"The mounted test directories are: {test_paths}.\n"
            "1. Start by listing files in these mounted directories, e.g., `list_files(path='/project/src', pattern='*')`.\n"
            "2. Do NOT try to list `/project` directly as it may not be accessible.\n"
            "3. Only drill down into specific directories if absolutely necessary.\n"
            "4. Only use `read_file` for critical configuration files or small, highly relevant source files.\n"
            "5. Never read large files or list entire directories recursively unless targeted.\n"
            "When providing relevant_files in the MicroSpec, ensure the paths are virtual paths from the sandbox, "
            "e.g., '/project/src/models.py'.")
        ,
        toolsets=[toolset],
    )