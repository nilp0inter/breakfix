"""Tests for inter-module dependency graph analysis."""
import pytest

from breakfix.distiller.module_graph import (
    ModuleInfo,
    topological_sort_modules,
)


class TestTopologicalSortModules:
    """Tests for topological_sort_modules function."""

    def test_empty_graph(self):
        """Empty graph should return empty list."""
        result = topological_sort_modules({})
        assert result == []

    def test_single_module_no_imports(self):
        """Single module with no imports."""
        modules = {
            "pkg.core": ModuleInfo(
                name="pkg.core",
                path="/path/to/core.py",
                imports=[],
                imported_by=[],
            )
        }
        result = topological_sort_modules(modules)
        assert result == ["pkg.core"]

    def test_two_independent_modules(self):
        """Two modules with no dependencies between them."""
        modules = {
            "pkg.a": ModuleInfo(name="pkg.a", path="/path/a.py", imports=[], imported_by=[]),
            "pkg.b": ModuleInfo(name="pkg.b", path="/path/b.py", imports=[], imported_by=[]),
        }
        result = topological_sort_modules(modules)
        assert len(result) == 2
        assert set(result) == {"pkg.a", "pkg.b"}

    def test_simple_dependency(self):
        """Module A imports module B - B should come first."""
        modules = {
            "pkg.a": ModuleInfo(
                name="pkg.a",
                path="/path/a.py",
                imports=["pkg.b"],
                imported_by=[],
            ),
            "pkg.b": ModuleInfo(
                name="pkg.b",
                path="/path/b.py",
                imports=[],
                imported_by=["pkg.a"],
            ),
        }
        result = topological_sort_modules(modules)
        assert result.index("pkg.b") < result.index("pkg.a")

    def test_chain_dependency(self):
        """A -> B -> C should produce [C, B, A]."""
        modules = {
            "pkg.a": ModuleInfo(
                name="pkg.a",
                path="/path/a.py",
                imports=["pkg.b"],
                imported_by=[],
            ),
            "pkg.b": ModuleInfo(
                name="pkg.b",
                path="/path/b.py",
                imports=["pkg.c"],
                imported_by=["pkg.a"],
            ),
            "pkg.c": ModuleInfo(
                name="pkg.c",
                path="/path/c.py",
                imports=[],
                imported_by=["pkg.b"],
            ),
        }
        result = topological_sort_modules(modules)
        assert result.index("pkg.c") < result.index("pkg.b")
        assert result.index("pkg.b") < result.index("pkg.a")

    def test_diamond_dependency(self):
        """Diamond: A -> B, A -> C, B -> D, C -> D."""
        modules = {
            "pkg.a": ModuleInfo(
                name="pkg.a",
                path="/path/a.py",
                imports=["pkg.b", "pkg.c"],
                imported_by=[],
            ),
            "pkg.b": ModuleInfo(
                name="pkg.b",
                path="/path/b.py",
                imports=["pkg.d"],
                imported_by=["pkg.a"],
            ),
            "pkg.c": ModuleInfo(
                name="pkg.c",
                path="/path/c.py",
                imports=["pkg.d"],
                imported_by=["pkg.a"],
            ),
            "pkg.d": ModuleInfo(
                name="pkg.d",
                path="/path/d.py",
                imports=[],
                imported_by=["pkg.b", "pkg.c"],
            ),
        }
        result = topological_sort_modules(modules)

        # D must come before B and C
        assert result.index("pkg.d") < result.index("pkg.b")
        assert result.index("pkg.d") < result.index("pkg.c")

        # B and C must come before A
        assert result.index("pkg.b") < result.index("pkg.a")
        assert result.index("pkg.c") < result.index("pkg.a")

    def test_external_import_ignored(self):
        """External imports (not in our package) should be ignored."""
        modules = {
            "pkg.main": ModuleInfo(
                name="pkg.main",
                path="/path/main.py",
                imports=["external.lib"],  # Not in modules dict
                imported_by=[],
            ),
        }
        result = topological_sort_modules(modules)
        assert result == ["pkg.main"]

    def test_circular_dependency_handled(self):
        """Circular dependencies should not cause infinite loop."""
        modules = {
            "pkg.a": ModuleInfo(
                name="pkg.a",
                path="/path/a.py",
                imports=["pkg.b"],
                imported_by=["pkg.b"],
            ),
            "pkg.b": ModuleInfo(
                name="pkg.b",
                path="/path/b.py",
                imports=["pkg.a"],
                imported_by=["pkg.a"],
            ),
        }
        result = topological_sort_modules(modules)
        # Both modules should be in result despite cycle
        assert len(result) == 2
        assert set(result) == {"pkg.a", "pkg.b"}

    def test_real_world_example(self):
        """Test with the example from user's description."""
        modules = {
            "thedump": ModuleInfo(
                name="thedump",
                path=None,  # Package __init__
                imports=[],
                imported_by=["thedump.parser"],
            ),
            "thedump.cli": ModuleInfo(
                name="thedump.cli",
                path="/path/cli.py",
                imports=["thedump.idea_capture", "thedump.parser"],
                imported_by=[],
            ),
            "thedump.idea_capture": ModuleInfo(
                name="thedump.idea_capture",
                path="/path/idea_capture/__init__.py",
                imports=["thedump.idea_capture.core", "thedump.idea_capture.model", "thedump.idea_capture.shell"],
                imported_by=["thedump.cli"],
            ),
            "thedump.idea_capture.core": ModuleInfo(
                name="thedump.idea_capture.core",
                path="/path/idea_capture/core.py",
                imports=["thedump.idea_capture.model"],
                imported_by=["thedump.idea_capture"],
            ),
            "thedump.idea_capture.model": ModuleInfo(
                name="thedump.idea_capture.model",
                path="/path/idea_capture/model.py",
                imports=[],
                imported_by=["thedump.idea_capture", "thedump.idea_capture.core", "thedump.idea_capture.shell"],
            ),
            "thedump.idea_capture.shell": ModuleInfo(
                name="thedump.idea_capture.shell",
                path="/path/idea_capture/shell.py",
                imports=["thedump.idea_capture.model"],
                imported_by=["thedump.idea_capture"],
            ),
            "thedump.parser": ModuleInfo(
                name="thedump.parser",
                path="/path/parser.py",
                imports=["thedump"],
                imported_by=["thedump.cli"],
            ),
        }
        result = topological_sort_modules(modules)

        # model has no internal dependencies, should be early
        assert result.index("thedump.idea_capture.model") < result.index("thedump.idea_capture.core")
        assert result.index("thedump.idea_capture.model") < result.index("thedump.idea_capture.shell")

        # core and shell depend on model
        assert result.index("thedump.idea_capture.core") < result.index("thedump.idea_capture")
        assert result.index("thedump.idea_capture.shell") < result.index("thedump.idea_capture")

        # cli depends on idea_capture and parser
        assert result.index("thedump.idea_capture") < result.index("thedump.cli")
        assert result.index("thedump.parser") < result.index("thedump.cli")
