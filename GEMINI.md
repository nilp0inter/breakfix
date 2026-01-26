# BreakFix - Project Context

## Project Overview

**BreakFix** is an autonomous, multi-agent software development engine designed to solve the single biggest problem with AI coding: **Hallucination.**

Most AI coding tools try to be "smart" by guessing what you want, often resulting in bloated, buggy, or untested code. BreakFix takes the opposite approach. It relies on **Extreme Test-Driven Development (TDD)** and **Adversarial Collaboration**.

In BreakFix, no single AI is trusted to do the whole job. Instead, 7 specialized agents watch, correct, and even "attack" each other to ensure the final code is mathematically perfect.

### The Philosophy
**"If it's not tested, it doesn't exist. If it's not minimal, it gets deleted."**

BreakFix operates on a cycle of destruction and creation. We force agents to write Failing Tests (Red), create minimal Code (Green), and then ruthlessly attack that code (Mutation Testing) to prove it's robust.

### The Team: 7 Specialists
1.  **The Architect (The Planner):** Turns feature requests into atomic "Micro-Specs".
2.  **The Pioneer (The Tester):** Writes failing tests based on the spec.
3.  **The Gatekeeper (The Reviewer):** Rejects scope creep in tests.
4.  **The Builder (The Coder):** Writes minimal code to pass tests.
5.  **The Pruner (The Cynic):** Deletes dead/unused code using coverage reports.
6.  **The Sniper (The Attacker):** Uses Mutation Testing to sabotage code and expose weak tests.
7.  **The Curator (The Cleaner):** Refactors code and tests for elegance.

## Tech Stack

*   **Language:** Python (>=3.13)
*   **Package Manager:** [uv](https://github.com/astral-sh/uv)
*   **Core Libraries:**
    *   `pydantic-ai`: Framework for building production-grade GenAI agents.
    *   `pydantic-ai-filesystem-sandbox`: Sandboxing utilities for Pydantic AI agents.
*   **Testing:** `pytest`

## Building and Running

This project uses `uv` to manage the virtual environment and dependencies.

### 1. Install Dependencies

To create the virtual environment and install both runtime and development dependencies:

```bash
uv sync
```

### 2. Running the Application

To run the CLI application:

```bash
uv run breakfix
```

### 3. Running Tests

To execute the test suite:

```bash
uv run pytest
```

## Project Structure

*   **`breakfix/`**: The main package directory.
    *   **`cli.py`**: The CLI entrypoint.
    *   **`__init__.py`**: Package marker.
*   **`pyproject.toml`**: Defines project metadata, dependencies, and configuration.
*   **`uv.lock`**: precise versions of installed dependencies to ensure reproducible builds.
*   **`pydantic-ai.docs.txt`**: Local documentation reference for `pydantic-ai`.

## Development Conventions

*   **Dependency Management**: Always use `uv add <package>` or `uv remove <package>` to manage dependencies. Do not manually edit `uv.lock`.
*   **Code Style**: Follow standard Python PEP 8 guidelines.
*   **Python Version**: Ensure compatibility with Python 3.13+.