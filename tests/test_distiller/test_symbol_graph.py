"""Tests for intra-module symbol graph analysis."""
import tempfile
from pathlib import Path

import pytest

from breakfix.distiller.symbol_graph import (
    analyze_module,
    topological_sort_symbols,
    get_sorted_symbols,
    Symbol,
)


def write_temp_module(content: str) -> Path:
    """Write content to a temporary Python file."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    f.write(content)
    f.close()
    return Path(f.name)


class TestAnalyzeModule:
    """Tests for analyze_module function."""

    def test_simple_function(self):
        """Test extraction of a simple function."""
        path = write_temp_module("""
def hello():
    return "world"
""")
        symbols = analyze_module(path, "test")

        assert len(symbols) == 1
        assert symbols[0].name == "hello"
        assert symbols[0].fqn == "test.hello"
        assert symbols[0].symbol_type == "function"
        assert symbols[0].dependencies == []

    def test_function_with_parameter(self):
        """Parameters should not be treated as dependencies."""
        path = write_temp_module("""
def greet(name):
    return f"Hello, {name}"
""")
        symbols = analyze_module(path, "test")

        assert len(symbols) == 1
        assert symbols[0].dependencies == []

    def test_function_calling_another(self):
        """A function calling another function should have it as dependency."""
        path = write_temp_module("""
def helper():
    return 42

def main():
    return helper()
""")
        symbols = analyze_module(path, "test")

        assert len(symbols) == 2
        helper = next(s for s in symbols if s.name == "helper")
        main = next(s for s in symbols if s.name == "main")

        assert helper.dependencies == []
        assert "helper" in main.dependencies

    def test_function_using_import(self):
        """A function using an imported name should have it as dependency."""
        path = write_temp_module("""
from os import path

def get_dir(filepath):
    return path.dirname(filepath)
""")
        symbols = analyze_module(path, "test")

        func = next(s for s in symbols if s.name == "get_dir")
        assert "path" in func.dependencies

    def test_function_with_local_variable(self):
        """Local variables should not be treated as dependencies."""
        path = write_temp_module("""
def compute():
    result = 42
    return result
""")
        symbols = analyze_module(path, "test")

        assert len(symbols) == 1
        assert symbols[0].dependencies == []

    def test_class_definition(self):
        """Test extraction of a class."""
        path = write_temp_module("""
class MyClass:
    def method(self):
        pass
""")
        symbols = analyze_module(path, "test")

        assert len(symbols) == 1
        assert symbols[0].name == "MyClass"
        assert symbols[0].symbol_type == "class"

    def test_class_with_base(self):
        """A class inheriting from another should have it as dependency."""
        path = write_temp_module("""
class Base:
    pass

class Derived(Base):
    pass
""")
        symbols = analyze_module(path, "test")

        derived = next(s for s in symbols if s.name == "Derived")
        assert "Base" in derived.dependencies

    def test_module_level_constant(self):
        """Test extraction of module-level constants."""
        path = write_temp_module("""
MAX_SIZE = 100
""")
        symbols = analyze_module(path, "test")

        assert len(symbols) == 1
        assert symbols[0].name == "MAX_SIZE"
        assert symbols[0].symbol_type == "constant"

    def test_constant_referencing_another(self):
        """A constant using another constant should have it as dependency."""
        path = write_temp_module("""
BASE = 10
DERIVED = BASE * 2
""")
        symbols = analyze_module(path, "test")

        derived = next(s for s in symbols if s.name == "DERIVED")
        assert "BASE" in derived.dependencies

    def test_import_statement(self):
        """Test extraction of import statements."""
        path = write_temp_module("""
import os
from pathlib import Path
""")
        symbols = analyze_module(path, "test")

        assert len(symbols) == 2
        os_import = next(s for s in symbols if s.name == "os")
        path_import = next(s for s in symbols if s.name == "Path")

        assert os_import.symbol_type == "import"
        assert path_import.symbol_type == "import"
        assert os_import.fqn == "os"
        assert path_import.fqn == "pathlib.Path"

    def test_decorator_dependency(self):
        """Decorators should be treated as dependencies."""
        path = write_temp_module("""
def my_decorator(func):
    return func

@my_decorator
def decorated():
    pass
""")
        symbols = analyze_module(path, "test")

        decorated = next(s for s in symbols if s.name == "decorated")
        assert "my_decorator" in decorated.dependencies

    def test_type_annotation_dependency(self):
        """Type annotations should be treated as dependencies."""
        path = write_temp_module("""
class MyType:
    pass

def process(value: MyType) -> MyType:
    return value
""")
        symbols = analyze_module(path, "test")

        process = next(s for s in symbols if s.name == "process")
        assert "MyType" in process.dependencies

    def test_comprehension_variable_not_dependency(self):
        """Comprehension loop variables should not be dependencies."""
        path = write_temp_module("""
def squares():
    return [x * x for x in range(10)]
""")
        symbols = analyze_module(path, "test")

        assert len(symbols) == 1
        # 'x' should not appear as a dependency
        assert "x" not in symbols[0].dependencies

    def test_builtin_not_dependency(self):
        """Builtins should not be treated as dependencies."""
        path = write_temp_module("""
def show(items):
    print(len(items))
    return list(items)
""")
        symbols = analyze_module(path, "test")

        func = symbols[0]
        assert "print" not in func.dependencies
        assert "len" not in func.dependencies
        assert "list" not in func.dependencies


class TestTopologicalSortSymbols:
    """Tests for topological_sort_symbols function."""

    def test_independent_symbols(self):
        """Symbols with no dependencies can be in any order."""
        symbols = [
            Symbol("a", "test.a", "function", 1, 2, "def a(): pass", []),
            Symbol("b", "test.b", "function", 3, 4, "def b(): pass", []),
        ]
        sorted_symbols = topological_sort_symbols(symbols)

        assert len(sorted_symbols) == 2
        names = [s.name for s in sorted_symbols]
        assert "a" in names
        assert "b" in names

    def test_simple_dependency(self):
        """Symbol with dependency should come after its dependency."""
        symbols = [
            Symbol("main", "test.main", "function", 3, 4, "def main(): helper()", ["helper"]),
            Symbol("helper", "test.helper", "function", 1, 2, "def helper(): pass", []),
        ]
        sorted_symbols = topological_sort_symbols(symbols)

        names = [s.name for s in sorted_symbols]
        assert names.index("helper") < names.index("main")

    def test_chain_dependency(self):
        """Chain of dependencies should be ordered correctly."""
        symbols = [
            Symbol("c", "test.c", "function", 5, 6, "def c(): b()", ["b"]),
            Symbol("a", "test.a", "function", 1, 2, "def a(): pass", []),
            Symbol("b", "test.b", "function", 3, 4, "def b(): a()", ["a"]),
        ]
        sorted_symbols = topological_sort_symbols(symbols)

        names = [s.name for s in sorted_symbols]
        assert names.index("a") < names.index("b")
        assert names.index("b") < names.index("c")


class TestGetSortedSymbols:
    """Integration tests for get_sorted_symbols."""

    def test_full_module(self):
        """Test analysis and sorting of a complete module."""
        path = write_temp_module("""
import json

CONFIG = {"debug": True}

def load_config(path):
    with open(path) as f:
        return json.load(f)

def get_setting(key):
    return CONFIG.get(key)

def main():
    config = load_config("config.json")
    debug = get_setting("debug")
    return debug
""")
        sorted_symbols = get_sorted_symbols(path, "mymodule")

        names = [s.name for s in sorted_symbols]

        # json import and CONFIG constant should come before functions that use them
        assert names.index("json") < names.index("load_config")
        assert names.index("CONFIG") < names.index("get_setting")

        # main depends on load_config and get_setting
        assert names.index("load_config") < names.index("main")
        assert names.index("get_setting") < names.index("main")
