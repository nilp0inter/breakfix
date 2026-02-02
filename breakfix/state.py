"""Pydantic models for state management in Prefect flows."""

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from breakfix.agents import ProjectMetadata, TestFixture


class TestCase(BaseModel):
    """A single test case specification from the Oracle."""

    id: int
    description: str
    test_function_name: str = ""


class UnitWorkItem(BaseModel):
    """A unit of work for TDD reconstruction."""

    name: str = Field(description="FQN, e.g., 'thedump.parser.parse_line'")
    tests: List[TestCase] = Field(default_factory=list)
    code: str = ""
    module_path: str = ""
    line_number: int = 0
    end_line_number: int = 0
    symbol_type: str = ""
    dependencies: List[str] = Field(default_factory=list)
    description: str = ""


class ProjectState(BaseModel):
    """State that flows through the project pipeline."""

    user_idea: str
    working_directory: str
    spec: str = ""
    fixtures: List[TestFixture] = Field(default_factory=list)
    project_metadata: Optional[ProjectMetadata] = None
    prototype_code: str = ""
    refined_arch: str = ""
    unit_queue: List[UnitWorkItem] = Field(default_factory=list)
    finished_units: List[str] = Field(default_factory=list)
    interface_description: str = ""

    model_config = {"arbitrary_types_allowed": True}
