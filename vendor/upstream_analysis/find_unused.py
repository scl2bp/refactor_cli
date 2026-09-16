"""
Unused function evaluator and remover.

This tool intentionally focuses on two responsibilities only:
1) Evaluate and report unused function/method symbols.
2) Optionally remove unused top-level functions from source files.

Quality-gate enforcement belongs to tools/quality_gate_report.py.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SCAN_PATHS: list[str] = ["src/felvi_games", "tests", "tools"]
SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
)


@dataclass
class UnusedSymbol:
    file: str
    name: str
    line: int
    end_line: int
    kind: str
    owner: str | None


@dataclass
class UnusedReport:
    generated_at_utc: str
    scanned_paths: list[str]
    python_files: int
    symbols_defined: int
    symbols_unused: int
    prefix_filter: str | None
    unused: list[dict]


def _iter_py_files(roots: Iterable[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            rp = root.resolve()
            if rp not in seen:
                seen.add(rp)
                result.append(rp)
            continue
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            rp = path.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            result.append(rp)
    return result


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _collect_definitions(tree: ast.AST, rel_path: str, prefix: str | None) -> list[UnusedSymbol]:
    defs: list[UnusedSymbol] = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._class_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._class_stack.append(node.name)
            self.generic_visit(node)
            self._class_stack.pop()

        def _add(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            if prefix and not node.name.startswith(prefix):
                return
            # Skip dunder methods — they are called implicitly by the runtime
            # and will never appear as a direct name reference.
            if node.name.startswith("__") and node.name.endswith("__"):
                return
            kind = "method" if self._class_stack else "function"
            owner = self._class_stack[-1] if self._class_stack else None
            defs.append(
                UnusedSymbol(
                    file=rel_path,
                    name=node.name,
                    line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    kind=kind,
                    owner=owner,
                )
            )

        visit_FunctionDef = _add  # type: ignore[assignment]
        visit_AsyncFunctionDef = _add  # type: ignore[assignment]

    _Visitor().visit(tree)
    return defs


def _collect_references(tree: ast.AST) -> set[str]:
    refs: set[str] = set()

    class _RefVisitor(ast.NodeVisitor):
        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Load, ast.Del)):
                refs.add(node.id)
            self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute) -> None:
            refs.add(node.attr)
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name):
                refs.add(node.func.id)
            self.generic_visit(node)

    _RefVisitor().visit(tree)
    return refs


# Decorator attribute names that indicate a function is registered externally
# and should not be counted as unused even if no direct call site exists.
_REGISTRATION_DECORATOR_ATTRS: frozenset[str] = frozenset({
    "command",   # @app.command(), @typer_app.command()
    "callback",  # @app.callback()
    "fixture",   # @pytest.fixture
    "mark",      # @pytest.mark.*
})


def _collect_decorator_registered_names(tree: ast.AST) -> set[str]:
    """Return names of functions that carry a registration decorator.

    A function is considered externally registered when any of its decorators
    is a Call or Attribute whose final attribute name is in
    _REGISTRATION_DECORATOR_ATTRS (e.g. @app.command(), @pytest.fixture).
    Such functions are treated as implicitly referenced and excluded from the
    unused-symbol report.
    """
    registered: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            # @something.command() — Call node wrapping an Attribute
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if dec.func.attr in _REGISTRATION_DECORATOR_ATTRS:
                    registered.add(node.name)
                    break
            # @something.command — bare Attribute (without call parens)
            elif isinstance(dec, ast.Attribute):
                if dec.attr in _REGISTRATION_DECORATOR_ATTRS:
                    registered.add(node.name)
                    break
            # @fixture — bare Name
            elif isinstance(dec, ast.Name):
                if dec.id in _REGISTRATION_DECORATOR_ATTRS:
                    registered.add(node.name)
                    break
    return registered


def analyse(py_files: list[Path], repo_root: Path, prefix: str | None = None) -> tuple[list[UnusedSymbol], int]:
    all_defs: list[UnusedSymbol] = []
    all_refs: set[str] = set()

    for py_file in py_files:
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        rel = _rel(py_file, repo_root)
        all_defs.extend(_collect_definitions(tree, rel, prefix))
        all_refs |= _collect_references(tree)
        all_refs |= _collect_decorator_registered_names(tree)

    unused = [d for d in all_defs if d.name not in all_refs]
    return unused, len(all_defs)


def _remove_unused_functions(unused: list[UnusedSymbol], repo_root: Path, *, backup: bool) -> int:
    removable = [s for s in unused if s.kind == "function" and s.owner is None]
    by_file: dict[str, list[UnusedSymbol]] = {}
    for sym in removable:
        by_file.setdefault(sym.file, []).append(sym)

    removed = 0
    for rel_path, symbols in by_file.items():
        target = repo_root / Path(rel_path)
        if not target.exists():
            continue

        text = target.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)

        if backup:
            backup_path = target.with_suffix(target.suffix + ".bak")
            backup_path.write_text(text, encoding="utf-8")

        for sym in sorted(symbols, key=lambda s: s.line, reverse=True):
            start = max(1, sym.line)
            end = max(start, sym.end_line)
            while start > 1 and lines[start - 2].strip() == "":
                start -= 1
            del lines[start - 1 : end]
            removed += 1

        target.write_text("".join(lines), encoding="utf-8")

    return removed


def render_report(report: UnusedReport) -> str:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("UNUSED SYMBOL REPORT")
    lines.append("=" * 70)
    lines.append(f"Generated : {report.generated_at_utc}")
    lines.append(f"Scanned   : {', '.join(report.scanned_paths)}")
    lines.append(f"Prefix    : {report.prefix_filter or '(all)'}")
    lines.append(f"Files     : {report.python_files}")
    lines.append(f"Defined   : {report.symbols_defined}")
    lines.append(f"Unused    : {report.symbols_unused}")
    lines.append("")

    if report.unused:
        lines.append(f"{'File:Line':<50}  {'Kind':<8}  {'Name'}")
        lines.append("-" * 90)
        for sym_dict in report.unused:
            sym = UnusedSymbol(**sym_dict)
            loc = f"{sym.file}:{sym.line}"
            owner_str = f" (in {sym.owner})" if sym.owner else ""
            lines.append(f"{loc:<50}  {sym.kind:<8}  {sym.name}{owner_str}")
    else:
        lines.append("No unused symbols detected.")

    lines.append("=" * 70)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Find and optionally remove unused functions.")
    parser.add_argument("--file", default=None, help="Scan a single file or folder.")
    parser.add_argument("--prefix", default=None, help="Only consider symbols whose names start with this prefix.")
    parser.add_argument("--json", action="store_true", help="Emit full report as JSON.")
    parser.add_argument("--remove", action="store_true", help="Remove detected unused top-level functions.")
    parser.add_argument("--backup", action="store_true", help="Create .bak backups before --remove edits.")
    args = parser.parse_args()

    repo_root = Path.cwd()
    scan_roots = [Path(args.file)] if args.file else [Path(p) for p in DEFAULT_SCAN_PATHS]

    py_files = _iter_py_files(scan_roots)
    if not py_files:
        print("ERROR: no Python files found in the specified paths.", file=sys.stderr)
        sys.exit(2)

    unused, total_defined = analyse(py_files, repo_root, prefix=args.prefix)
    report = UnusedReport(
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        scanned_paths=[str(r) for r in scan_roots],
        python_files=len(py_files),
        symbols_defined=total_defined,
        symbols_unused=len(unused),
        prefix_filter=args.prefix,
        unused=[asdict(s) for s in unused],
    )

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(render_report(report))

    if args.remove:
        removed = _remove_unused_functions(unused, repo_root, backup=args.backup)
        print(f"Removed {removed} unused top-level function(s).")


if __name__ == "__main__":
    main()
