"""Tests for Oracle agent functionality."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breakfix.agents.oracle.agent import (
    create_oracle,
    run_oracle,
    OracleResult,
    OracleOutput,
    TestCaseDescription,
)
from breakfix.nodes import UnitWorkItem, TestCase


class TestCreateOracle:
    """Tests for create_oracle function."""

    def test_returns_agent(self):
        """Should return a Pydantic AI Agent."""
        # Use a mock to avoid API key requirement
        with patch("breakfix.agents.oracle.agent.Agent") as mock_agent_class:
            mock_agent_class.return_value = MagicMock()
            agent = create_oracle()

            mock_agent_class.assert_called_once()
            call_kwargs = mock_agent_class.call_args
            assert call_kwargs.kwargs["output_type"] == OracleOutput
            assert "system_prompt" in call_kwargs.kwargs

    def test_custom_model(self):
        """Should accept custom model parameter."""
        with patch("breakfix.agents.oracle.agent.Agent") as mock_agent_class:
            mock_agent_class.return_value = MagicMock()
            create_oracle(model="openai:gpt-4")

            call_args = mock_agent_class.call_args
            assert call_args.args[0] == "openai:gpt-4"


class TestRunOracleSkipping:
    """Tests for run_oracle skipping non-function/class units."""

    @pytest.mark.anyio
    async def test_skips_constants(self):
        """Should return empty test cases for constants."""
        unit = UnitWorkItem(
            name="pkg.constants.MAX_VALUE",
            code="MAX_VALUE = 100",
            symbol_type="constant",
        )

        result = await run_oracle(unit)

        assert result.success
        assert result.test_cases == []
        assert result.description == ""

    @pytest.mark.anyio
    async def test_skips_imports(self):
        """Should return empty test cases for imports."""
        unit = UnitWorkItem(
            name="pkg.module.os",
            code="import os",
            symbol_type="import",
        )

        result = await run_oracle(unit)

        assert result.success
        assert result.test_cases == []
        assert result.description == ""

    @pytest.mark.anyio
    async def test_skips_empty_symbol_type(self):
        """Should skip units with empty symbol_type."""
        unit = UnitWorkItem(
            name="pkg.unknown",
            code="something = 1",
            symbol_type="",
        )

        result = await run_oracle(unit)

        assert result.success
        assert result.test_cases == []


class TestRunOracleWithMockedLLM:
    """Tests for run_oracle with mocked LLM responses."""

    @pytest.mark.anyio
    async def test_processes_function(self):
        """Should generate test cases for functions."""
        unit = UnitWorkItem(
            name="pkg.core.calculate",
            code="def calculate(x, y):\n    return x + y",
            symbol_type="function",
            dependencies=["operator"],
        )

        mock_output = OracleOutput(
            description="Adds two numbers together and returns their sum. Takes x and y parameters.",
            test_cases=[
                TestCaseDescription(
                    test_function_name="test_calculate_two_positive_numbers",
                    scenario="Two positive numbers",
                    input_description="x=2, y=3",
                    expected_outcome="Returns 5",
                ),
                TestCaseDescription(
                    test_function_name="test_calculate_zero_inputs",
                    scenario="Zero inputs",
                    input_description="x=0, y=0",
                    expected_outcome="Returns 0",
                ),
            ],
        )

        mock_result = MagicMock()
        mock_result.output = mock_output

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value=mock_result)

        with patch("breakfix.agents.oracle.agent.create_oracle", return_value=mock_agent):
            result = await run_oracle(unit)

        assert result.success
        assert len(result.test_cases) == 2
        assert result.description == "Adds two numbers together and returns their sum. Takes x and y parameters."

        # Check test case formatting
        assert result.test_cases[0].id == 1
        assert "Scenario: Two positive numbers" in result.test_cases[0].description
        assert "Input: x=2, y=3" in result.test_cases[0].description
        assert "Expected: Returns 5" in result.test_cases[0].description

        assert result.test_cases[1].id == 2

    @pytest.mark.anyio
    async def test_processes_class(self):
        """Should generate test cases for classes."""
        unit = UnitWorkItem(
            name="pkg.core.Calculator",
            code="class Calculator:\n    def add(self, x, y):\n        return x + y",
            symbol_type="class",
        )

        mock_output = OracleOutput(
            description="A calculator class with an add method that sums two numbers together.",
            test_cases=[
                TestCaseDescription(
                    test_function_name="test_calculator_add_two_numbers",
                    scenario="Add two numbers",
                    input_description="calc.add(1, 2)",
                    expected_outcome="Returns 3",
                ),
            ],
        )

        mock_result = MagicMock()
        mock_result.output = mock_output

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value=mock_result)

        with patch("breakfix.agents.oracle.agent.create_oracle", return_value=mock_agent):
            result = await run_oracle(unit)

        assert result.success
        assert len(result.test_cases) == 1

    @pytest.mark.anyio
    async def test_handles_llm_error(self):
        """Should return error result when LLM fails."""
        unit = UnitWorkItem(
            name="pkg.core.calculate",
            code="def calculate(x):\n    return x",
            symbol_type="function",
        )

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(side_effect=Exception("LLM API error"))

        with patch("breakfix.agents.oracle.agent.create_oracle", return_value=mock_agent):
            result = await run_oracle(unit)

        assert not result.success
        assert "LLM API error" in result.error

    @pytest.mark.anyio
    async def test_sequential_ids(self):
        """Should assign sequential IDs to test cases."""
        unit = UnitWorkItem(
            name="pkg.core.process",
            code="def process(data):\n    return data.upper()",
            symbol_type="function",
        )

        mock_output = OracleOutput(
            description="Processes data by converting the input string to uppercase format.",
            test_cases=[
                TestCaseDescription(
                    test_function_name="test_process_hello",
                    scenario="Test 1",
                    input_description="data='hello'",
                    expected_outcome="Returns 'HELLO'",
                ),
                TestCaseDescription(
                    test_function_name="test_process_world",
                    scenario="Test 2",
                    input_description="data='world'",
                    expected_outcome="Returns 'WORLD'",
                ),
                TestCaseDescription(
                    test_function_name="test_process_empty_string",
                    scenario="Test 3",
                    input_description="data=''",
                    expected_outcome="Returns ''",
                ),
            ],
        )

        mock_result = MagicMock()
        mock_result.output = mock_output

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value=mock_result)

        with patch("breakfix.agents.oracle.agent.create_oracle", return_value=mock_agent):
            result = await run_oracle(unit)

        assert result.success
        assert len(result.test_cases) == 3
        assert result.test_cases[0].id == 1
        assert result.test_cases[1].id == 2
        assert result.test_cases[2].id == 3


class TestOracleResult:
    """Tests for OracleResult dataclass."""

    def test_success_result(self):
        """Should create a success result."""
        test_cases = [TestCase(id=1, description="Test 1")]
        result = OracleResult(
            success=True,
            test_cases=test_cases,
            description="Function description",
        )

        assert result.success
        assert result.test_cases == test_cases
        assert result.description == "Function description"
        assert result.error == ""

    def test_failure_result(self):
        """Should create a failure result."""
        result = OracleResult(success=False, error="Something went wrong")

        assert not result.success
        assert result.error == "Something went wrong"
        assert result.test_cases == []
        assert result.description == ""

    def test_default_values(self):
        """Should have correct default values."""
        result = OracleResult(success=True)

        assert result.success
        assert result.test_cases == []
        assert result.description == ""
        assert result.error == ""


class TestOracleOutput:
    """Tests for OracleOutput Pydantic model."""

    def test_valid_output(self):
        """Should validate correct output."""
        output = OracleOutput(
            description="A" * 50,  # Minimum 50 chars
            test_cases=[
                TestCaseDescription(
                    test_function_name="test_valid_scenario",
                    scenario="Test scenario",
                    input_description="Some input",
                    expected_outcome="Expected result",
                ),
            ],
        )

        assert len(output.description) >= 50
        assert len(output.test_cases) >= 1

    def test_description_too_short(self):
        """Should reject description shorter than 50 chars."""
        with pytest.raises(ValueError):
            OracleOutput(
                description="Too short",
                test_cases=[
                    TestCaseDescription(
                        test_function_name="test_short_description",
                        scenario="Test",
                        input_description="Input",
                        expected_outcome="Output",
                    ),
                ],
            )

    def test_empty_test_cases(self):
        """Should reject empty test cases list."""
        with pytest.raises(ValueError):
            OracleOutput(
                description="A" * 50,
                test_cases=[],
            )
