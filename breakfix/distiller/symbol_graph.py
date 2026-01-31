"""Intra-module dependency graph using Python AST."""
import ast
import builtins
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


BUILTINS = set(dir(builtins))


@dataclass
class Symbol:
    """A symbol extracted from a module."""
    name: str                    # Local name in module
    fqn: str                     # Fully qualified name
    symbol_type: str             # "function", "class", "constant", "import"
    line_number: int
    end_line_number: int
    source_code: str
    dependencies: List[str] = field(default_factory=list)  # Local names of dependencies


class DependencyFinder(ast.NodeVisitor):
    """Find all names used in a function/class body that are dependencies."""

    def __init__(self, parameters: Set[str], module_symbols: Set[str], imports: Dict[str, str]):
        self.parameters = parameters
        self.module_symbols = module_symbols
        self.imports = imports  # Maps local name -> FQN
        self.locals: Set[str] = set()
        self.dependencies: Set[str] = set()
        self._in_comprehension_target = False

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            name = node.id
            # Skip if it's a parameter, local, or builtin
            if name in self.parameters:
                return
            if name in self.locals:
                return
            if name in BUILTINS:
                return
            if self._in_comprehension_target:
                return
            # It's a dependency - either module-level or import
            if name in self.module_symbols or name in self.imports:
                self.dependencies.add(name)
        elif isinstance(node.ctx, ast.Store):
            # Track local assignments
            self.locals.add(node.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Nested function - the function name becomes a local
        self.locals.add(node.name)
        # Don't visit the body of nested functions (they're separate scopes)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.locals.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # Nested class - the class name becomes a local
        self.locals.add(node.name)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        # Comprehension targets are local to the comprehension
        self._in_comprehension_target = True
        self.visit(node.target)
        self._in_comprehension_target = False
        self.visit(node.iter)
        for if_ in node.ifs:
            self.visit(if_)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        for gen in node.generators:
            self.visit_comprehension(gen)
        self.visit(node.elt)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        for gen in node.generators:
            self.visit_comprehension(gen)
        self.visit(node.elt)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        for gen in node.generators:
            self.visit_comprehension(gen)
        self.visit(node.key)
        self.visit(node.value)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        for gen in node.generators:
            self.visit_comprehension(gen)
        self.visit(node.elt)


def _get_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Set[str]:
    """Extract parameter names from a function definition."""
    params: Set[str] = set()

    # Regular arguments
    for arg in node.args.args:
        params.add(arg.arg)

    # Positional-only arguments (Python 3.8+)
    for arg in node.args.posonlyargs:
        params.add(arg.arg)

    # Keyword-only arguments
    for arg in node.args.kwonlyargs:
        params.add(arg.arg)

    # *args
    if node.args.vararg:
        params.add(node.args.vararg.arg)

    # **kwargs
    if node.args.kwarg:
        params.add(node.args.kwarg.arg)

    return params


def _extract_source(source_lines: List[str], start: int, end: int) -> str:
    """Extract source code for a range of lines (1-indexed)."""
    return "\n".join(source_lines[start - 1:end])


def analyze_module(module_path: Path, module_fqn: str) -> List[Symbol]:
    """
    Parse a module with AST and extract all symbols with their dependencies.

    Args:
        module_path: Path to the Python module file
        module_fqn: Fully qualified name of the module (e.g., "mypackage.submodule")

    Returns:
        List of Symbol objects representing all top-level definitions
    """
    source = module_path.read_text()
    source_lines = source.splitlines()
    tree = ast.parse(source, filename=str(module_path))

    symbols: List[Symbol] = []
    module_symbol_names: Set[str] = set()
    imports: Dict[str, str] = {}  # Local name -> imported FQN

    # First pass: collect all top-level symbol names and imports
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module_symbol_names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            module_symbol_names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_symbol_names.add(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                module_symbol_names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name
                imports[local_name] = alias.name
                module_symbol_names.add(local_name)
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            for alias in node.names:
                local_name = alias.asname or alias.name
                if alias.name == "*":
                    # Star imports are complex - skip for now
                    continue
                fqn = f"{module_name}.{alias.name}" if module_name else alias.name
                imports[local_name] = fqn
                module_symbol_names.add(local_name)

    # Second pass: extract symbols with dependencies
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = _get_parameters(node)

            # Find dependencies in function body, decorators, annotations
            finder = DependencyFinder(params, module_symbol_names, imports)

            # Visit decorators
            for decorator in node.decorator_list:
                finder.visit(decorator)

            # Visit return annotation
            if node.returns:
                finder.visit(node.returns)

            # Visit argument annotations
            for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                if arg.annotation:
                    finder.visit(arg.annotation)
            if node.args.vararg and node.args.vararg.annotation:
                finder.visit(node.args.vararg.annotation)
            if node.args.kwarg and node.args.kwarg.annotation:
                finder.visit(node.args.kwarg.annotation)

            # Visit default values
            for default in node.args.defaults + node.args.kw_defaults:
                if default:
                    finder.visit(default)

            # Visit body
            for stmt in node.body:
                finder.visit(stmt)

            symbols.append(Symbol(
                name=node.name,
                fqn=f"{module_fqn}.{node.name}",
                symbol_type="function",
                line_number=node.lineno,
                end_line_number=node.end_lineno or node.lineno,
                source_code=_extract_source(source_lines, node.lineno, node.end_lineno or node.lineno),
                dependencies=list(finder.dependencies),
            ))

        elif isinstance(node, ast.ClassDef):
            # Find dependencies in class body, decorators, bases
            finder = DependencyFinder(set(), module_symbol_names, imports)

            # Visit decorators
            for decorator in node.decorator_list:
                finder.visit(decorator)

            # Visit base classes
            for base in node.bases:
                finder.visit(base)

            # Visit keywords (metaclass, etc.)
            for keyword in node.keywords:
                finder.visit(keyword.value)

            # Visit class body for class-level attributes
            for stmt in node.body:
                finder.visit(stmt)

            symbols.append(Symbol(
                name=node.name,
                fqn=f"{module_fqn}.{node.name}",
                symbol_type="class",
                line_number=node.lineno,
                end_line_number=node.end_lineno or node.lineno,
                source_code=_extract_source(source_lines, node.lineno, node.end_lineno or node.lineno),
                dependencies=list(finder.dependencies),
            ))

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    # Find dependencies in the assigned value
                    finder = DependencyFinder(set(), module_symbol_names, imports)
                    finder.visit(node.value)

                    symbols.append(Symbol(
                        name=target.id,
                        fqn=f"{module_fqn}.{target.id}",
                        symbol_type="constant",
                        line_number=node.lineno,
                        end_line_number=node.end_lineno or node.lineno,
                        source_code=_extract_source(source_lines, node.lineno, node.end_lineno or node.lineno),
                        dependencies=list(finder.dependencies),
                    ))

        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                finder = DependencyFinder(set(), module_symbol_names, imports)
                if node.value:
                    finder.visit(node.value)
                if node.annotation:
                    finder.visit(node.annotation)

                symbols.append(Symbol(
                    name=node.target.id,
                    fqn=f"{module_fqn}.{node.target.id}",
                    symbol_type="constant",
                    line_number=node.lineno,
                    end_line_number=node.end_lineno or node.lineno,
                    source_code=_extract_source(source_lines, node.lineno, node.end_lineno or node.lineno),
                    dependencies=list(finder.dependencies),
                ))

        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name
                symbols.append(Symbol(
                    name=local_name,
                    fqn=alias.name,
                    symbol_type="import",
                    line_number=node.lineno,
                    end_line_number=node.end_lineno or node.lineno,
                    source_code=_extract_source(source_lines, node.lineno, node.end_lineno or node.lineno),
                    dependencies=[],  # Imports have no internal dependencies
                ))

        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                fqn = f"{module_name}.{alias.name}" if module_name else alias.name
                symbols.append(Symbol(
                    name=local_name,
                    fqn=fqn,
                    symbol_type="import",
                    line_number=node.lineno,
                    end_line_number=node.end_lineno or node.lineno,
                    source_code=_extract_source(source_lines, node.lineno, node.end_lineno or node.lineno),
                    dependencies=[],
                ))

    return symbols


def topological_sort_symbols(symbols: List[Symbol]) -> List[Symbol]:
    """
    Topologically sort symbols within a module, emitting leaf nodes first.

    Leaf nodes are symbols with no internal dependencies.

    Args:
        symbols: List of Symbol objects from a module

    Returns:
        List of Symbol in topological order (leaves first)
    """
    if not symbols:
        return []

    # Build name -> symbol mapping
    by_name: Dict[str, Symbol] = {s.name: s for s in symbols}

    # Build in-degree (count of internal dependencies)
    in_degree: Dict[str, int] = defaultdict(int)
    dependents: Dict[str, List[str]] = defaultdict(list)

    for symbol in symbols:
        if symbol.name not in in_degree:
            in_degree[symbol.name] = 0

        for dep in symbol.dependencies:
            if dep in by_name:  # Only count internal dependencies
                in_degree[symbol.name] += 1
                dependents[dep].append(symbol.name)

    # Kahn's algorithm
    queue = [name for name, degree in in_degree.items() if degree == 0]
    result: List[str] = []

    while queue:
        queue.sort()  # Deterministic ordering
        current = queue.pop(0)
        result.append(current)

        for dependent in dependents[current]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    # Handle cycles
    if len(result) != len(symbols):
        remaining = [s.name for s in symbols if s.name not in result]
        result.extend(sorted(remaining))

    return [by_name[name] for name in result]


def get_sorted_symbols(module_path: Path, module_fqn: str) -> List[Symbol]:
    """
    Get symbols from a module in topological order (leaves first).

    Args:
        module_path: Path to the Python module file
        module_fqn: Fully qualified name of the module

    Returns:
        List of Symbol in topological order
    """
    symbols = analyze_module(module_path, module_fqn)
    return topological_sort_symbols(symbols)
