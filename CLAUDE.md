# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build/Development Commands

- **Install dependencies:** `uv sync`
- **Run application:** `uv run breakfix <working_dir>`
- **Run tests:** `uv run pytest`
- **Run single test:** `uv run pytest tests/test_file.py::test_function`
- **Add packages:** `uv add <package>`
- **Remove packages:** `uv remove <package>`

## Architecture Overview

BreakFix is a multi-agent TDD foundry that transforms user ideas into tested Python software through a series of phases. The system uses two agent frameworks:
- **Pydantic AI** for user-facing agents (structured output, interactive Q&A)
- **Claude Agent SDK** for code generation agents

### Execution Flow

The system is implemented as a state machine with checkpoint-based resumption:

```
User Idea → Specification → E2E Tests → Scaffold → Prototype → [Refine → Distill → Ratchet → Crucible]
```

Phases 1-2 are implemented. Phases 3-6 (refinement, distillation, ratchet TDD cycles, crucible hardening) are stubbed.

### Key Modules

**`breakfix/graph.py`** - State machine engine
- `run_graph()` - Executes node functions, handles `MoveToNode`, `FinalResult`, `NodeError`
- Checkpoint system saves state to `.breakfix/execution/*.pickle` for resumption

**`breakfix/nodes.py`** - Phase implementations as async node functions
- `start_project_node` → `phase_specification_node` → `phase_e2e_builder_node` → `phase_scaffold_node` → `phase_prototyping_node`
- Inner graph nodes for unit-level TDD: `ratchet_red_node`, `ratchet_green_node`, `crucible_*_node`
- `ProjectState` dataclass carries state through the pipeline

**`breakfix/runner.py`** - Dependency injection and execution entry point
- Creates `deps` namespace with agent factories and check functions
- Wires real implementations (subprocess calls, agent invocations)

### Agent Implementations (`breakfix/agents/`)

| Agent | Framework | Purpose |
|-------|-----------|---------|
| `analyst` | Pydantic AI | Interactive Q&A to capture requirements, fixtures, project metadata |
| `e2e_builder` | Claude Agent SDK | Creates `run_tests.py` and `mock_program.py` in `e2e-tests/` |
| `interface_analyzer` | Pydantic AI | Analyzes mock program to describe I/O interface |
| `prototyper` | Claude Agent SDK | Implements working prototype with feedback loop |

### Agent Pattern

Pydantic AI agents use `Agent()` with `output_type` for structured validation:
```python
agent = Agent(model, output_type=SomeModel, system_prompt=PROMPT, tools=[...])
async with agent.iter(user_input) as run:
    async for node in run:
        pass
    result = run.result.output
```

Claude Agent SDK agents use `query()` or `ClaudeSDKClient`:
```python
async for message in query(prompt=prompt, options=options):
    if isinstance(message, ResultMessage):
        # handle completion
```

### Data Flow

1. **Analyst** produces `AnalystOutput` (spec, fixtures, metadata)
2. **E2E Builder** creates test harness that fixtures can validate any implementation
3. **Interface Analyzer** extracts interface description from mock program
4. **Scaffolding** runs PyScaffold `putup` to create `prototype/` directory
5. **Prototyper** implements `prototype/src/{package}/skeleton.py` with feedback loop

## Code Conventions

- Python 3.13+ required
- Use `pathlib.Path` for file operations
- Agents return dataclass results with `success: bool` and `error: str`
- Node functions are async and receive `deps` as keyword argument
- Transition between nodes via `MoveToNode.with_parameters(next_fn, state)`

## Environment

Requires `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` depending on configured models.
