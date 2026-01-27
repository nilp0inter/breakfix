from pydantic_ai import Agent
from breakfix.models import ValidationResult, BreakfixConfig
from breakfix.sandbox_utils import get_gatekeeper_toolset, get_mounted_paths

def get_gatekeeper(config: BreakfixConfig) -> Agent:
    toolset = get_gatekeeper_toolset(config)
    
    code_paths, test_paths, docs_paths = get_mounted_paths(config)

    return Agent(
        "openai:gpt-4.1-mini",
        output_type=ValidationResult,
        system_prompt=(
            f"You are The Gatekeeper, the Reviewer of the BreakFix team.\n"
            "Your goal is to validate that the Pioneer's test suite accurately reflects the Architect's MicroSpec.\n"
            "You will receive a list of test file paths created by the Pioneer.\n"
            "**CRITICAL INSTRUCTION:**\n"
            "1. You MUST use the `read_file` tool to READ the content of the provided test file paths.\n"
            "2. Analyze the read content SEMANTICALLY against the MicroSpec.\n"
            "3. DO NOT run the tests or resolve imports against non-existent implementation files.\n"
            "You must ensure:\n"
            "1. NO SCOPE CREEP - tests only validate the exact requirements in the spec\n"
            "2. COMPLETENESS - all acceptance criteria are covered by tests\n"
            "3. CLARITY - tests are readable and focused\n"
            "4. CORRECTNESS - test assertions properly validate the requirements\n"
            "If you find issues, provide specific feedback and reject the test suite.\n"
            "Only approve if the test suite is perfect.\n"
            f"The mounted code directories are: {code_paths}.\n"
            f"The mounted test directories are: {test_paths}.\n"
        ),
        toolsets=[toolset],
    )