from pydantic import BaseModel, Field
from pathlib import Path
from typing import List

class MicroSpec(BaseModel):
    """
    A single, atomic requirement definition.
    """
    title: str = Field(..., description="A short, descriptive title for the feature.")
    user_story: str = Field(..., description="The user story or high-level goal.")
    requirement: str = Field(..., description="The specific, atomic technical requirement. Must be testable.")
    acceptance_criteria: List[str] = Field(..., description="List of specific criteria that define success.")
    relevant_files: List[str] = Field(default_factory=list, description="List of files relevant to this task.")

class BreakfixConfig(BaseModel):
    """
    Configuration for the Breakfix project, defining file system mounts for agents.
    """
    project_root: Path = Field(default=Path("."), description="The root directory of the project.")
    code_globs: List[str] = Field(default_factory=lambda: ["breakfix/**/*.py"], description="Glob patterns for code files.")
    test_globs: List[str] = Field(default_factory=lambda: ["tests/**/*.py"], description="Glob patterns for test files.")
    docs_globs: List[str] = Field(default_factory=lambda: ["*.md", "docs/**/*.md"], description="Glob patterns for documentation files.")