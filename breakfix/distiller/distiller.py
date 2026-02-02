"""Main distiller orchestrator - combines module and symbol graphs."""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from breakfix.state import UnitWorkItem, TestCase
from .module_graph import get_sorted_modules, ModuleInfo
from .symbol_graph import get_sorted_symbols, Symbol


@dataclass
class DistillerResult:
    """Result of the distillation process."""
    success: bool
    units: List[UnitWorkItem] = field(default_factory=list)
    error: str = ""


def _symbol_to_unit(symbol: Symbol, module_path: str) -> UnitWorkItem:
    """Convert a Symbol to a UnitWorkItem."""
    return UnitWorkItem(
        name=symbol.fqn,
        tests=[],  # Will be populated by Oracle later
        code=symbol.source_code,
        module_path=module_path,
        line_number=symbol.line_number,
        end_line_number=symbol.end_line_number,
        symbol_type=symbol.symbol_type,
        dependencies=symbol.dependencies,
    )


async def run_distiller(
    proto_dir: Path,
    package_name: str,
) -> DistillerResult:
    """
    Run the distillation process to decompose a prototype into atomic units.

    The process:
    1. Run pydeps to get inter-module dependency graph
    2. Topologically sort modules (leaf-first)
    3. For each module, run AST analysis to get symbols
    4. Topologically sort symbols within each module (leaf-first)
    5. Emit flat list of UnitWorkItem

    Args:
        proto_dir: Path to the prototype/ directory
        package_name: Name of the package to analyze

    Returns:
        DistillerResult with success status and list of UnitWorkItem
    """
    src_dir = proto_dir / "src"

    try:
        # Step 1-2: Get modules in topological order
        logging.info(f"[DISTILLER] Analyzing module graph for {package_name}")
        sorted_modules = get_sorted_modules(src_dir, package_name)
        logging.info(f"[DISTILLER] Found {len(sorted_modules)} modules")

        # Step 3-4: For each module, get symbols in topological order
        all_units: List[UnitWorkItem] = []

        for module_info in sorted_modules:
            if not module_info.path:
                continue

            module_path = Path(module_info.path)
            logging.info(f"[DISTILLER] Analyzing {module_info.name}")

            sorted_symbols = get_sorted_symbols(module_path, module_info.name)
            logging.info(f"[DISTILLER]   Found {len(sorted_symbols)} symbols")

            # Convert symbols to UnitWorkItem
            for symbol in sorted_symbols:
                unit = _symbol_to_unit(symbol, module_info.path)
                all_units.append(unit)

        logging.info(f"[DISTILLER] Total units: {len(all_units)}")
        return DistillerResult(success=True, units=all_units)

    except Exception as e:
        logging.exception(f"[DISTILLER] Failed: {e}")
        return DistillerResult(success=False, error=str(e))
