import time

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from breakfix.artifacts import agent_input_artifact, agent_output_artifact


class InterfaceDescription(BaseModel):
    """Structured description of a program's I/O interface."""
    summary: str = Field(description="One-line summary of what the program does")
    input_method: str = Field(description="How input is received (stdin, HTTP POST, CLI args, etc.)")
    output_method: str = Field(description="How output is produced (stdout, HTTP response, etc.)")
    input_format: str = Field(description="Format of input data (JSON, plain text, line-by-line, etc.)")
    output_format: str = Field(description="Format of output data (JSON, plain text, etc.)")
    protocol_details: str = Field(description="Protocol specifics: port, endpoints, headers, encoding, etc.")
    invocation: str = Field(description="Exact command to run the program (e.g., './program' or 'python program.py')")
    example_interaction: str = Field(description="A concrete example showing input and expected output")


INTERFACE_ANALYZER_PROMPT = """You are analyzing a Python program to describe its I/O interface.

Given the source code, describe EXACTLY how the program communicates:
- What does it read? (stdin, HTTP requests, files, CLI arguments)
- What does it write? (stdout, HTTP responses, files)
- What format/protocol does it use? (JSON, plain text, specific ports, etc.)

IMPORTANT: Describe the interface when the program is invoked WITHOUT any arguments
or environment variables. Just: ./program.py or python program.py

Be extremely specific. If it's an HTTP server, specify the port and endpoints.
If it reads stdin, specify the expected format line-by-line.
If it uses JSON, show the exact schema.

The goal is for another developer to implement a compatible program without seeing this code."""


def create_interface_analyzer(model: str = "openai:gpt-5-mini") -> Agent[None, InterfaceDescription]:
    """Create the Interface Analyzer agent."""
    return Agent(
        model,
        output_type=InterfaceDescription,
        system_prompt=INTERFACE_ANALYZER_PROMPT,
    )


async def analyze_interface(mock_program_code: str, model: str = "openai:gpt-5-mini") -> InterfaceDescription:
    """Analyze a program's interface from its source code."""
    start_time = time.time()

    print("[INTERFACE-ANALYZER] ========================================")
    print(f"[INTERFACE-ANALYZER] Analyzing mock program interface")
    print(f"[INTERFACE-ANALYZER] Model: {model}")
    print(f"[INTERFACE-ANALYZER] Code length: {len(mock_program_code)} chars")
    print("[INTERFACE-ANALYZER] ========================================")

    prompt = f"Analyze this program's interface:\n\n```python\n{mock_program_code}\n```"

    await agent_input_artifact(
        agent_name="interface-analyzer",
        prompt=prompt[:1000] + "...(truncated)" if len(prompt) > 1000 else prompt,
        context={
            "model": model,
            "code_length": len(mock_program_code),
        },
    )

    agent = create_interface_analyzer(model)
    result = await agent.run(prompt)
    output = result.output

    duration = time.time() - start_time

    print(f"[INTERFACE-ANALYZER] Summary: {output.summary}")
    print(f"[INTERFACE-ANALYZER] Input method: {output.input_method}")
    print(f"[INTERFACE-ANALYZER] Output method: {output.output_method}")
    print(f"[INTERFACE-ANALYZER] Duration: {duration:.1f}s")

    await agent_output_artifact(
        agent_name="interface-analyzer",
        result=f"Summary: {output.summary}\nInput: {output.input_method} ({output.input_format})\nOutput: {output.output_method} ({output.output_format})\nInvocation: {output.invocation}",
        success=True,
        duration_seconds=duration,
    )

    return output
