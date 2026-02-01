"""Tests for production code cleanup functionality."""
import tempfile
from pathlib import Path

import pytest

from breakfix.nodes import UnitWorkItem
from breakfix.workspace.cleanup import (
    stub_function_body,
    process_file,
    get_target_files,
    cleanup_production_code,
    CleanupResult,
)
import ast


class TestStubFunctionBody:
    """Tests for stub_function_body function."""

    def test_simple_function(self):
        """Should replace body with raise NotImplementedError."""
        source = """
def calculate(x, y):
    result = x + y
    return result
"""
        tree = ast.parse(source)
        func = tree.body[0]

        stub_function_body(func)

        # Should have exactly one statement: raise NotImplementedError
        assert len(func.body) == 1
        assert isinstance(func.body[0], ast.Raise)

    def test_preserves_docstring(self):
        """Should preserve docstring when stubbing."""
        source = '''
def calculate(x, y):
    """Add two numbers together."""
    result = x + y
    return result
'''
        tree = ast.parse(source)
        func = tree.body[0]

        stub_function_body(func)

        # Should have docstring + raise
        assert len(func.body) == 2
        assert isinstance(func.body[0], ast.Expr)
        assert isinstance(func.body[0].value, ast.Constant)
        assert func.body[0].value.value == "Add two numbers together."
        assert isinstance(func.body[1], ast.Raise)

    def test_async_function(self):
        """Should work with async functions."""
        source = """
async def fetch_data(url):
    response = await client.get(url)
    return response
"""
        tree = ast.parse(source)
        func = tree.body[0]

        stub_function_body(func)

        assert len(func.body) == 1
        assert isinstance(func.body[0], ast.Raise)

    def test_empty_function(self):
        """Should handle function with just pass."""
        source = """
def placeholder():
    pass
"""
        tree = ast.parse(source)
        func = tree.body[0]

        stub_function_body(func)

        assert len(func.body) == 1
        assert isinstance(func.body[0], ast.Raise)


class TestProcessFile:
    """Tests for process_file function."""

    def test_stubs_all_functions(self):
        """Should stub all functions in a file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
def func1():
    return 1

def func2():
    return 2

def func3():
    return 3
''')
            f.flush()
            path = Path(f.name)

        count = process_file(path)

        assert count == 3

        # Verify the file was modified
        new_source = path.read_text()
        assert "NotImplementedError" in new_source
        assert "return 1" not in new_source

    def test_stubs_class_methods(self):
        """Should stub all methods in classes."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
class MyClass:
    def __init__(self):
        self.value = 0

    def method1(self):
        return self.value

    def method2(self, x):
        self.value = x
''')
            f.flush()
            path = Path(f.name)

        count = process_file(path)

        # 3 methods: __init__, method1, method2
        assert count == 3

    def test_preserves_decorators(self):
        """Should preserve decorators on functions."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
@property
def my_prop(self):
    return self._value

@staticmethod
def static_method():
    return 42
''')
            f.flush()
            path = Path(f.name)

        count = process_file(path)

        assert count == 2

        new_source = path.read_text()
        assert "@property" in new_source
        assert "@staticmethod" in new_source

    def test_preserves_type_annotations(self):
        """Should preserve type annotations."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
def typed_func(x: int, y: str) -> bool:
    return True
''')
            f.flush()
            path = Path(f.name)

        process_file(path)

        new_source = path.read_text()
        assert "int" in new_source
        assert "str" in new_source
        assert "bool" in new_source


class TestGetTargetFiles:
    """Tests for get_target_files function."""

    def test_filters_shell_and_core(self):
        """Should only return shell.py and core.py files."""
        unit_queue = [
            UnitWorkItem(name="pkg.shell.func1", module_path="/project/production/src/pkg/shell.py"),
            UnitWorkItem(name="pkg.core.func2", module_path="/project/production/src/pkg/core.py"),
            UnitWorkItem(name="pkg.utils.helper", module_path="/project/production/src/pkg/utils.py"),
            UnitWorkItem(name="pkg.parser.parse", module_path="/project/production/src/pkg/parser.py"),
        ]

        target_files = get_target_files(unit_queue)

        assert len(target_files) == 2
        assert Path("/project/production/src/pkg/shell.py") in target_files
        assert Path("/project/production/src/pkg/core.py") in target_files

    def test_includes_nested_paths(self):
        """Should include shell.py files in nested directories."""
        unit_queue = [
            UnitWorkItem(
                name="pkg.subpkg.shell.func",
                module_path="/project/production/src/pkg/subpkg/shell.py"
            ),
        ]

        target_files = get_target_files(unit_queue)

        assert Path("/project/production/src/pkg/subpkg/shell.py") in target_files

    def test_deduplicates_files(self):
        """Should return unique files even if multiple units from same file."""
        unit_queue = [
            UnitWorkItem(name="pkg.shell.func1", module_path="/project/production/src/pkg/shell.py"),
            UnitWorkItem(name="pkg.shell.func2", module_path="/project/production/src/pkg/shell.py"),
            UnitWorkItem(name="pkg.shell.func3", module_path="/project/production/src/pkg/shell.py"),
        ]

        target_files = get_target_files(unit_queue)

        assert len(target_files) == 1

    def test_handles_empty_module_path(self):
        """Should skip units with empty module_path."""
        unit_queue = [
            UnitWorkItem(name="pkg.shell.func1", module_path=""),
            UnitWorkItem(name="pkg.shell.func2", module_path="/project/production/src/pkg/shell.py"),
        ]

        target_files = get_target_files(unit_queue)

        assert len(target_files) == 1


class TestCleanupProductionCode:
    """Integration tests for cleanup_production_code."""

    @pytest.fixture
    def temp_prod_dir(self):
        """Create temporary production directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            prod_dir = tmpdir / "production"
            src_pkg = prod_dir / "src" / "mypkg"
            src_pkg.mkdir(parents=True)

            (src_pkg / "shell.py").write_text('''
def read_file(path):
    """Read a file from disk."""
    with open(path) as f:
        return f.read()

def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)
''')

            (src_pkg / "core.py").write_text('''
def process(data):
    """Process the data."""
    return data.upper()

def validate(data):
    return len(data) > 0
''')

            (src_pkg / "utils.py").write_text('''
def helper():
    return 42
''')

            yield prod_dir

    @pytest.mark.anyio
    async def test_stubs_shell_and_core(self, temp_prod_dir):
        """Should stub functions in shell.py and core.py."""
        prod_dir = temp_prod_dir

        unit_queue = [
            UnitWorkItem(
                name="mypkg.shell.read_file",
                module_path=str(prod_dir / "src" / "mypkg" / "shell.py"),
                symbol_type="function",
            ),
            UnitWorkItem(
                name="mypkg.core.process",
                module_path=str(prod_dir / "src" / "mypkg" / "core.py"),
                symbol_type="function",
            ),
            UnitWorkItem(
                name="mypkg.utils.helper",
                module_path=str(prod_dir / "src" / "mypkg" / "utils.py"),
                symbol_type="function",
            ),
        ]

        result = await cleanup_production_code(unit_queue)

        assert result.success
        assert result.files_modified == 2  # shell.py and core.py
        assert result.functions_stubbed == 4  # 2 in shell + 2 in core

        # Verify shell.py was stubbed
        shell_content = (prod_dir / "src" / "mypkg" / "shell.py").read_text()
        assert "NotImplementedError" in shell_content
        assert "open(path)" not in shell_content
        # Docstring should be preserved
        assert "Read a file from disk" in shell_content

        # Verify core.py was stubbed
        core_content = (prod_dir / "src" / "mypkg" / "core.py").read_text()
        assert "NotImplementedError" in core_content
        assert "data.upper()" not in core_content

        # Verify utils.py was NOT touched
        utils_content = (prod_dir / "src" / "mypkg" / "utils.py").read_text()
        assert "return 42" in utils_content
        assert "NotImplementedError" not in utils_content

    @pytest.mark.anyio
    async def test_empty_unit_queue(self, temp_prod_dir):
        """Should handle empty unit queue."""
        result = await cleanup_production_code([])

        assert result.success
        assert result.files_modified == 0
        assert result.functions_stubbed == 0


class TestCleanupResult:
    """Tests for CleanupResult dataclass."""

    def test_success_result(self):
        """Should create a success result."""
        result = CleanupResult(success=True, files_modified=2, functions_stubbed=10)
        assert result.success
        assert result.files_modified == 2
        assert result.functions_stubbed == 10
        assert result.error == ""

    def test_failure_result(self):
        """Should create a failure result."""
        result = CleanupResult(success=False, error="File not found")
        assert not result.success
        assert result.error == "File not found"
