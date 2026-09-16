from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType


def _load_upstream_gate() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "vendor" / "upstream_analysis" / "quality_gate_report.py"
    if not script_path.exists():
        raise FileNotFoundError(
            f"Vendored quality gate implementation not found: {script_path}"
        )
    spec = importlib.util.spec_from_file_location("refactor_cli_upstream_quality_gate", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load quality gate implementation: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_quality_gate(arguments: list[str]) -> int:
    """Run the vendored complexity gate with CLI-compatible arguments."""
    module = _load_upstream_gate()
    original_argv = sys.argv
    try:
        sys.argv = [str(Path(module.__file__ or "quality_gate_report.py")), *arguments]
        return int(module.main())
    finally:
        sys.argv = original_argv