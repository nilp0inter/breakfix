# AGENTS.md

## Build/Development Commands

**Install dependencies:** `uv sync`
**Run application:** `uv run breakfix`
**Run tests:** `uv run pytest`
**Run single test:** `uv run pytest tests/test_file.py::test_function`
**Add packages:** `uv add <package>`
**Remove packages:** `uv remove <package>`
**Lint/Format:** No specific commands configured (add in pyproject.toml if needed)

## Code Style Guidelines

- Python 3.13+ required
- Use `uv` for package management
- Follow PEP 8 formatting
- Type hints with `from typing import List` and Pydantic models
- Error handling with try/except blocks in main flows
- Import organization: standard library, third-party, local modules
- CLI entry point: `breakfix/cli.py:main`
- Agent pattern: Use pydantic_ai Agent with output_type validation
- File paths: Use pathlib.Path for path operations
- Environment variables: Check required keys before execution (e.g., OPENAI_API_KEY)
- Dependency management: Always use `uv add/remove`, never edit uv.lock manually