"""Tests for Ratchet Red Phase (Tester Agent) functionality."""
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breakfix.agents.ratchet_red.agent import (
    run_ratchet_red,
    RatchetRedResult,
    permission_handler,
    TESTER_SYSTEM_PROMPT,
    _extract_signature,
)
from breakfix.agents.ratchet_red.validator import (
    validate_test,
    ValidationResult,
    create_test_validator,
)
from breakfix.nodes import UnitWorkItem, TestCase


class TestPermissionHandler:
    """Tests for permission_handler function."""

    def test_blocks_bash_execution(self):
        """Should deny Bash tool usage."""
        tests_dir = Path("/production/tests")
        unit_file_path = Path("/production/src/core.py")

        result = permission_handler("Bash", {"command": "pytest"}, tests_dir, unit_file_path)

        assert hasattr(result, "message")
        assert "not allowed" in result.message.lower()

    def test_blocks_bashoutput(self):
        """Should deny BashOutput tool usage."""
        tests_dir = Path("/production/tests")
        unit_file_path = Path("/production/src/core.py")

        result = permission_handler("BashOutput", {}, tests_dir, unit_file_path)

        assert hasattr(result, "message")

    def test_allows_write_to_tests_dir(self):
        """Should allow Write to tests/ directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tests_dir = Path(tmpdir) / "tests"
            tests_dir.mkdir()
            unit_file_path = Path(tmpdir) / "src" / "core.py"
            file_path = str(tests_dir / "test_core.py")

            result = permission_handler("Write", {"file_path": file_path}, tests_dir, unit_file_path)

            assert hasattr(result, "updated_input")

    def test_denies_write_outside_tests_dir(self):
        """Should deny Write outside tests/ directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tests_dir = Path(tmpdir) / "tests"
            tests_dir.mkdir()
            unit_file_path = Path(tmpdir) / "src" / "unit.py"
            file_path = str(Path(tmpdir) / "src" / "other.py")

            result = permission_handler("Write", {"file_path": file_path}, tests_dir, unit_file_path)

            assert hasattr(result, "message")
            assert "only allowed" in result.message.lower()

    def test_allows_read_anywhere(self):
        """Should allow Read from any location (except unit file)."""
        tests_dir = Path("/production/tests")
        unit_file_path = Path("/production/src/core.py")

        result = permission_handler("Read", {"file_path": "/some/other/path.py"}, tests_dir, unit_file_path)

        assert hasattr(result, "updated_input")

    def test_blocks_read_unit_file(self):
        """Should deny Read access to the unit implementation file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tests_dir = Path(tmpdir) / "tests"
            tests_dir.mkdir()
            unit_file_path = Path(tmpdir) / "src" / "core.py"

            result = permission_handler("Read", {"file_path": str(unit_file_path)}, tests_dir, unit_file_path)

            assert hasattr(result, "message")
            assert "access denied" in result.message.lower()

    def test_blocks_write_unit_file(self):
        """Should deny Write access to the unit implementation file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tests_dir = Path(tmpdir) / "tests"
            tests_dir.mkdir()
            unit_file_path = Path(tmpdir) / "src" / "core.py"

            result = permission_handler("Write", {"file_path": str(unit_file_path)}, tests_dir, unit_file_path)

            assert hasattr(result, "message")
            assert "access denied" in result.message.lower()

    def test_blocks_edit_unit_file(self):
        """Should deny Edit access to the unit implementation file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tests_dir = Path(tmpdir) / "tests"
            tests_dir.mkdir()
            unit_file_path = Path(tmpdir) / "src" / "core.py"

            result = permission_handler("Edit", {"file_path": str(unit_file_path)}, tests_dir, unit_file_path)

            assert hasattr(result, "message")
            assert "access denied" in result.message.lower()

    def test_allows_glob(self):
        """Should allow Glob tool."""
        tests_dir = Path("/production/tests")
        unit_file_path = Path("/production/src/core.py")

        result = permission_handler("Glob", {"pattern": "**/*.py"}, tests_dir, unit_file_path)

        assert hasattr(result, "updated_input")

    def test_allows_grep(self):
        """Should allow Grep tool."""
        tests_dir = Path("/production/tests")
        unit_file_path = Path("/production/src/core.py")

        result = permission_handler("Grep", {"pattern": "test_"}, tests_dir, unit_file_path)

        assert hasattr(result, "updated_input")


class TestRatchetRedResult:
    """Tests for RatchetRedResult dataclass."""

    def test_success_result(self):
        """Should create a success result."""
        result = RatchetRedResult(
            success=True,
            test_file_path="tests/test_core.py::test_calculate",
            retries=0,
        )

        assert result.success
        assert result.test_file_path == "tests/test_core.py::test_calculate"
        assert result.retries == 0
        assert result.error == ""

    def test_failure_result(self):
        """Should create a failure result."""
        result = RatchetRedResult(
            success=False,
            error="Expected exactly 1 new test, got 0",
            retries=3,
        )

        assert not result.success
        assert "1 new test" in result.error
        assert result.retries == 3

    def test_default_values(self):
        """Should have correct default values."""
        result = RatchetRedResult(success=True)

        assert result.success
        assert result.test_file_path == ""
        assert result.error == ""
        assert result.retries == 0


class TestValidationResult:
    """Tests for ValidationResult model."""

    def test_valid_result(self):
        """Should create a valid result."""
        result = ValidationResult(is_valid=True)

        assert result.is_valid
        assert result.reason == ""

    def test_invalid_result_with_reason(self):
        """Should create an invalid result with reason."""
        result = ValidationResult(
            is_valid=False,
            reason="Test does not match the expected scenario"
        )

        assert not result.is_valid
        assert "scenario" in result.reason.lower()


class TestCreateTestValidator:
    """Tests for create_test_validator function."""

    def test_returns_agent(self):
        """Should return a Pydantic AI Agent."""
        with patch("breakfix.agents.ratchet_red.validator.Agent") as mock_agent_class:
            mock_agent_class.return_value = MagicMock()
            agent = create_test_validator()

            mock_agent_class.assert_called_once()
            call_kwargs = mock_agent_class.call_args
            assert call_kwargs.kwargs["output_type"] == ValidationResult

    def test_custom_model(self):
        """Should accept custom model parameter."""
        with patch("breakfix.agents.ratchet_red.validator.Agent") as mock_agent_class:
            mock_agent_class.return_value = MagicMock()
            create_test_validator(model="openai:gpt-4")

            call_args = mock_agent_class.call_args
            assert call_args.args[0] == "openai:gpt-4"


class TestValidateTest:
    """Tests for validate_test function."""

    @pytest.fixture
    def temp_production_dir(self):
        """Create temporary production directory with test file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            tests_dir = tmpdir / "tests"
            tests_dir.mkdir()

            # Create a test file
            test_file = tests_dir / "test_core.py"
            test_file.write_text('''
def test_calculate_positive():
    """Test adding two positive numbers."""
    from mypackage.core import calculate
    result = calculate(2, 3)
    assert result == 5
''')

            yield tmpdir

    @pytest.mark.anyio
    async def test_validates_test_file(self, temp_production_dir):
        """Should validate a test file against specification."""
        tests_dir = temp_production_dir / "tests"

        mock_result = MagicMock()
        mock_result.output = ValidationResult(is_valid=True)

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value=mock_result)

        with patch("breakfix.agents.ratchet_red.validator.create_test_validator", return_value=mock_agent):
            result = await validate_test(
                unit_name="mypackage.core.calculate",
                unit_code="def calculate(x, y):\n    raise NotImplementedError()",
                test_spec="Scenario: Two positive numbers\nInput: x=2, y=3\nExpected: Returns 5",
                test_file_path="tests/test_core.py::test_calculate_positive",
                tests_dir=tests_dir,
            )

        assert result.is_valid

    @pytest.mark.anyio
    async def test_returns_invalid_for_missing_file(self, temp_production_dir):
        """Should return invalid if test file doesn't exist."""
        tests_dir = temp_production_dir / "tests"

        result = await validate_test(
            unit_name="mypackage.core.calculate",
            unit_code="def calculate(x, y): pass",
            test_spec="Some spec",
            test_file_path="tests/nonexistent.py::test_something",
            tests_dir=tests_dir,
        )

        assert not result.is_valid
        assert "not found" in result.reason.lower()

    @pytest.mark.anyio
    async def test_handles_validation_error(self, temp_production_dir):
        """Should handle validation errors gracefully."""
        tests_dir = temp_production_dir / "tests"

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(side_effect=Exception("LLM API error"))

        with patch("breakfix.agents.ratchet_red.validator.create_test_validator", return_value=mock_agent):
            result = await validate_test(
                unit_name="mypackage.core.calculate",
                unit_code="def calculate(x, y): pass",
                test_spec="Some spec",
                test_file_path="tests/test_core.py::test_calculate_positive",
                tests_dir=tests_dir,
            )

        assert not result.is_valid
        assert "error" in result.reason.lower()


class TestTesterSystemPrompt:
    """Tests for the system prompt."""

    def test_prompt_mentions_one_test(self):
        """Prompt should emphasize writing exactly one test."""
        assert "ONE" in TESTER_SYSTEM_PROMPT or "one" in TESTER_SYSTEM_PROMPT.lower()
        assert "exactly" in TESTER_SYSTEM_PROMPT.lower()

    def test_prompt_mentions_failing_test(self):
        """Prompt should mention test must fail."""
        assert "fail" in TESTER_SYSTEM_PROMPT.lower()

    def test_prompt_mentions_tests_directory(self):
        """Prompt should mention tests/ directory."""
        assert "tests/" in TESTER_SYSTEM_PROMPT


class TestRunRatchetRedWithMocks:
    """Tests for run_ratchet_red with mocked Claude SDK."""

    @pytest.fixture
    def unit(self):
        """Create a test unit."""
        return UnitWorkItem(
            name="mypackage.core.calculate",
            code="def calculate(x, y):\n    raise NotImplementedError()",
            module_path="/production/src/mypackage/core.py",
            symbol_type="function",
            description="Adds two numbers and returns their sum.",
        )

    @pytest.fixture
    def test_case(self):
        """Create a test case."""
        return TestCase(
            id=1,
            description="Scenario: Two positive numbers\nInput: x=2, y=3\nExpected: Returns 5",
        )

    @pytest.fixture
    def temp_production_dir(self):
        """Create temporary production directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            tests_dir = tmpdir / "tests"
            tests_dir.mkdir()
            yield tmpdir

    @pytest.mark.anyio
    async def test_success_with_one_new_test(self, unit, test_case, temp_production_dir):
        """Should succeed when exactly one new test is added."""
        # Create the expected test file (file existence check happens before inventory check)
        test_file_dir = temp_production_dir / "tests" / "unit" / "mypackage" / "core"
        test_file_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_file_dir / "test_calculate.py"
        test_file.write_text("def test_calculate(): pass")

        # Mock get_test_inventory to return different sets before/after
        inventory_calls = [0]
        def mock_get_inventory(tests_dir):
            inventory_calls[0] += 1
            if inventory_calls[0] == 1:
                return set()  # Before
            return {"tests/unit/mypackage/core/test_calculate.py::test_calculate_positive"}  # After

        # Mock validate_test to return valid
        mock_validation = ValidationResult(is_valid=True)

        # Mock ClaudeSDKClient
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.query = AsyncMock()

        # Create async generator for receive_response
        async def mock_receive():
            # Use MagicMock to simulate ResultMessage
            mock_result = MagicMock()
            mock_result.is_error = False
            mock_result.result = "Done"
            yield mock_result

        mock_client.receive_response = mock_receive

        with patch("breakfix.agents.ratchet_red.agent.ClaudeSDKClient", return_value=mock_client):
            with patch("breakfix.agents.ratchet_red.agent.validate_test", return_value=mock_validation):
                with patch("breakfix.agents.ratchet_red.agent.ResultMessage", MagicMock):
                    result = await run_ratchet_red(
                        unit=unit,
                        test_case=test_case,
                        production_dir=temp_production_dir,
                        get_test_inventory=mock_get_inventory,
                    )

        assert result.success
        assert result.test_file_path == "tests/unit/mypackage/core/test_calculate.py::test_calculate_positive"

    @pytest.mark.anyio
    async def test_fails_with_no_new_tests(self, unit, test_case, temp_production_dir):
        """Should fail when no new tests are added."""
        # Create the expected test file (file existence check passes)
        test_file_dir = temp_production_dir / "tests" / "unit" / "mypackage" / "core"
        test_file_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_file_dir / "test_calculate.py"
        test_file.write_text("def test_calculate(): pass")

        # Mock get_test_inventory to return same set before/after (no new tests)
        def mock_get_inventory(tests_dir):
            return set()

        # Mock ClaudeSDKClient
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.query = AsyncMock()
        mock_client.rewind_files = AsyncMock()

        async def mock_receive():
            mock_result = MagicMock()
            mock_result.is_error = False
            mock_result.result = "Done"
            yield mock_result

        mock_client.receive_response = mock_receive

        with patch("breakfix.agents.ratchet_red.agent.ClaudeSDKClient", return_value=mock_client):
            with patch("breakfix.agents.ratchet_red.agent.ResultMessage", MagicMock):
                result = await run_ratchet_red(
                    unit=unit,
                    test_case=test_case,
                    production_dir=temp_production_dir,
                    get_test_inventory=mock_get_inventory,
                    max_retries=1,
                )

        assert not result.success
        assert "0" in result.error  # "got 0"

    @pytest.mark.anyio
    async def test_fails_with_multiple_new_tests(self, unit, test_case, temp_production_dir):
        """Should fail when multiple new tests are added."""
        # Create the expected test file (file existence check passes)
        test_file_dir = temp_production_dir / "tests" / "unit" / "mypackage" / "core"
        test_file_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_file_dir / "test_calculate.py"
        test_file.write_text("def test_calculate(): pass")

        inventory_calls = [0]
        def mock_get_inventory(tests_dir):
            inventory_calls[0] += 1
            if inventory_calls[0] == 1:
                return set()
            return {
                "tests/unit/mypackage/core/test_calculate.py::test_calculate_positive",
                "tests/unit/mypackage/core/test_calculate.py::test_calculate_negative",
            }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.query = AsyncMock()
        mock_client.rewind_files = AsyncMock()

        async def mock_receive():
            mock_result = MagicMock()
            mock_result.is_error = False
            mock_result.result = "Done"
            yield mock_result

        mock_client.receive_response = mock_receive

        with patch("breakfix.agents.ratchet_red.agent.ClaudeSDKClient", return_value=mock_client):
            with patch("breakfix.agents.ratchet_red.agent.ResultMessage", MagicMock):
                result = await run_ratchet_red(
                    unit=unit,
                    test_case=test_case,
                    production_dir=temp_production_dir,
                    get_test_inventory=mock_get_inventory,
                    max_retries=1,
                )

        assert not result.success
        assert "2" in result.error  # "got 2"

    @pytest.mark.anyio
    async def test_fails_when_validation_rejects(self, unit, test_case, temp_production_dir):
        """Should fail when Pydantic AI validator rejects the test."""
        # Create the expected test file (file existence check passes)
        test_file_dir = temp_production_dir / "tests" / "unit" / "mypackage" / "core"
        test_file_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_file_dir / "test_calculate.py"
        test_file.write_text("def test_calculate(): pass")

        inventory_calls = [0]
        def mock_get_inventory(tests_dir):
            inventory_calls[0] += 1
            if inventory_calls[0] == 1:
                return set()
            return {"tests/unit/mypackage/core/test_calculate.py::test_calculate"}

        # Validation rejects
        mock_validation = ValidationResult(
            is_valid=False,
            reason="Test does not match specification - wrong inputs used"
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.query = AsyncMock()
        mock_client.rewind_files = AsyncMock()

        async def mock_receive():
            mock_result = MagicMock()
            mock_result.is_error = False
            mock_result.result = "Done"
            yield mock_result

        mock_client.receive_response = mock_receive

        with patch("breakfix.agents.ratchet_red.agent.ClaudeSDKClient", return_value=mock_client):
            with patch("breakfix.agents.ratchet_red.agent.ResultMessage", MagicMock):
                with patch("breakfix.agents.ratchet_red.agent.validate_test", return_value=mock_validation):
                    result = await run_ratchet_red(
                        unit=unit,
                        test_case=test_case,
                        production_dir=temp_production_dir,
                        get_test_inventory=mock_get_inventory,
                        max_retries=1,
                    )

        assert not result.success
        assert "validation failed" in result.error.lower()



class TestExtractSignature:
    """Tests for _extract_signature function."""

    def test_simple_function(self):
        """Should extract function signature with body replaced by ..."""
        code = """def calculate(a: int, b: int) -> int:
    \"\"\"Add two numbers.\"\"\"
    return a + b"""

        result = _extract_signature(code)

        assert "def calculate(a: int, b: int) -> int:" in result
        assert "Add two numbers" in result
        assert "return a + b" not in result
        assert "..." in result

    def test_function_without_docstring(self):
        """Should handle function without docstring."""
        code = """def calculate(a: int, b: int) -> int:
    return a + b"""

        result = _extract_signature(code)

        assert "def calculate" in result
        assert "return a + b" not in result
        assert "..." in result

    def test_async_function(self):
        """Should handle async functions."""
        code = """async def fetch_data(url: str) -> dict:
    \"\"\"Fetch data from URL.\"\"\"
    response = await client.get(url)
    return response.json()"""

        result = _extract_signature(code)

        assert "async def fetch_data" in result
        assert "Fetch data from URL" in result
        assert "await" not in result
        assert "..." in result

    def test_multiline_docstring(self):
        """Should preserve multiline docstrings."""
        code = """def process(data: list) -> list:
    \"\"\"Process the data.
    
    Args:
        data: Input data list
    
    Returns:
        Processed data
    \"\"\"
    result = []
    for item in data:
        result.append(item * 2)
    return result"""

        result = _extract_signature(code)

        assert "def process" in result
        assert "Process the data" in result
        assert "Args:" in result
        assert "Returns:" in result
        assert "result = []" not in result
        assert "..." in result

    def test_empty_code(self):
        """Should handle empty code."""
        result = _extract_signature("")

        assert result == ""

    def test_class_definition(self):
        """Should handle class definitions."""
        code = """class Calculator:
    \"\"\"A simple calculator.\"\"\"
    
    def __init__(self):
        self.value = 0"""

        result = _extract_signature(code)

        assert "class Calculator:" in result
        assert "A simple calculator" in result
        assert "self.value = 0" not in result

