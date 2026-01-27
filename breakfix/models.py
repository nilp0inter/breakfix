from pydantic import BaseModel, Field
from pathlib import Path
from typing import List


class MicroSpec(BaseModel):
    """
    A single, atomic requirement definition.
    """

    title: str = Field(..., description="A short, descriptive title for the feature.")
    user_story: str = Field(..., description="The user story or high-level goal.")
    requirement: str = Field(
        ..., description="The specific, atomic technical requirement. Must be testable."
    )
    acceptance_criteria: List[str] = Field(
        ..., description="List of specific criteria that define success."
    )
    relevant_files: List[str] = Field(
        default_factory=list, description="List of files relevant to this task."
    )


class TestCase(BaseModel):
    """
    A single test case definition.
    """

    test_function_name: str = Field(
        ..., description="Name of the test function (e.g., test_function_name)."
    )
    test_file_path: str = Field(
        ..., description="Path where the test should be created."
    )
    test_code: str = Field(
        ..., description="Complete test code including imports and assertions."
    )
    description: str = Field(..., description="What this test validates.")


class TestSuite(BaseModel):
    """
    A collection of test cases for a MicroSpec.
    """

    micro_spec_title: str = Field(
        ..., description="Title of the MicroSpec this test suite validates."
    )
    test_cases: List[TestCase] = Field(..., description="List of test cases.")
    setup_code: str = Field(default="", description="Setup code needed for tests.")


class ValidationResult(BaseModel):
    """
    Result of Gatekeeper validation.
    """

    approved: bool = Field(..., description="Whether the test suite is approved.")
    feedback: str = Field(..., description="Feedback on what needs to be fixed.")
    issues: List[str] = Field(
        default_factory=list, description="Specific issues found."
    )


class CodeImplementation(BaseModel):
    """
    Code implementation from Builder agent.
    """

    file_path: str = Field(..., description="Path where code should be placed.")
    code: str = Field(..., description="Complete implementation code.")
    description: str = Field(..., description="What this code implements.")


class CoverageReport(BaseModel):
    """
    Analysis of code coverage from Pruner agent.
    """

    unused_lines: List[str] = Field(
        default_factory=list,
        description="Lines of code that are not executed by tests.",
    )
    dead_functions: List[str] = Field(
        default_factory=list, description="Functions that are never called."
    )
    recommendations: List[str] = Field(
        ..., description="What should be removed or improved."
    )
    coverage_percentage: float = Field(
        ..., description="Percentage of code covered by tests."
    )


class MutationTestResult(BaseModel):
    """
    Results from Sniper mutation testing.
    """

    mutations_survived: List[str] = Field(
        ..., description="Mutations that were not caught by tests."
    )
    tests_to_add: List[str] = Field(
        ..., description="New test cases needed to catch survivors."
    )
    weakness_score: float = Field(
        ..., description="How weak the test suite is (0-100)."
    )


class RefactoredCode(BaseModel):
    """
    Refactored code and tests from Curator agent.
    """

    improved_files: List[str] = Field(
        ..., description="List of files that were improved."
    )
    improvements_made: List[str] = Field(
        ..., description="Specific improvements and refactorings performed."
    )
    code_quality_score: float = Field(
        ..., description="Overall code quality rating (0-100)."
    )
    description: str = Field(..., description="Summary of the curation work performed.")


class BreakfixConfig(BaseModel):
    """
    Configuration for the Breakfix project, defining file system mounts for agents.
    """

    project_root: Path = Field(
        default=Path("."), description="The root directory of the project."
    )
    code_globs: List[str] = Field(
        default_factory=lambda: ["breakfix/**/*.py"],
        description="Glob patterns for code files.",
    )
    test_globs: List[str] = Field(
        default_factory=lambda: ["tests/**/*.py"],
        description="Glob patterns for test files.",
    )
    docs_globs: List[str] = Field(
        default_factory=lambda: ["*.md", "docs/**/*.md"],
        description="Glob patterns for documentation files.",
    )
