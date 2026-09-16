from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any


def _python_files(scope_path: Path) -> list[Path]:
    if scope_path.is_file():
        return [scope_path] if scope_path.suffix == ".py" else []
    return sorted(
        path
        for path in scope_path.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _module_name(path: Path, package_root: Path, package: str) -> str:
    relative = path.relative_to(package_root)
    if relative.name == "__init__.py":
        parts = relative.parts[:-1]
    else:
        parts = (*relative.with_suffix("").parts,)
    return ".".join((package, *parts))


def _resolve_relative(current: str, level: int, name: str | None) -> str:
    parts = current.split(".")[:-1]
    anchor = parts[: max(0, len(parts) - level + 1)]
    return ".".join((*anchor, *(name.split(".") if name else ())))


def _nearest(name: str, known: set[str]) -> str | None:
    candidate = name
    while candidate:
        if candidate in known:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


def _imports(tree: ast.AST, current: str, package: str, known: set[str]) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = (
                _resolve_relative(current, node.level, node.module)
                if node.level
                else (node.module or "")
            )
            names = [f"{base}.{alias.name}" for alias in node.names]
            if base:
                names.append(base)
        else:
            continue
        for name in names:
            if name == package or name.startswith(f"{package}."):
                target = _nearest(name, known)
                if target and target != current:
                    result.add(target)
    return result


def _complexity(tree: ast.AST) -> int:
    return 1 + sum(
        isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.BoolOp, ast.IfExp))
        for node in ast.walk(tree)
    )


def _normalized_hash(node: ast.AST) -> str:
    class Normalize(ast.NodeTransformer):
        def visit_Name(self, current: ast.Name) -> ast.AST:
            return ast.copy_location(ast.Name(id="name", ctx=current.ctx), current)

        def visit_arg(self, current: ast.arg) -> ast.AST:
            return ast.copy_location(ast.arg(arg="arg", annotation=current.annotation, type_comment=None), current)

        def visit_Constant(self, current: ast.Constant) -> ast.AST:
            value = "literal" if isinstance(current.value, (str, bytes)) else current.value
            if isinstance(current.value, (int, float, complex)):
                value = 0
            return ast.copy_location(ast.Constant(value=value), current)

    normalized = Normalize().visit(ast.fix_missing_locations(node))
    return hashlib.sha1(ast.dump(normalized, include_attributes=False).encode(), usedforsecurity=False).hexdigest()


def _unused_functions(trees: dict[Path, ast.AST], relative: dict[Path, str]) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    references: set[str] = set()
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("__") and node.name.endswith("__"):
                    continue
                definitions.append({"name": node.name, "file": relative[path], "line": node.lineno})
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                references.add(node.id)
    return [item for item in definitions if item["name"] not in references]


def collect_quality_report(*, project_root: Path, scope_path: Path) -> dict[str, Any]:
    files = _python_files(scope_path)
    package_root = scope_path if scope_path.is_dir() else scope_path.parent
    package = package_root.name
    relative = {path: path.relative_to(project_root).as_posix() for path in files}
    trees: dict[Path, ast.AST] = {}
    parse_errors: list[str] = []
    for path in files:
        try:
            trees[path] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            parse_errors.append(relative[path])

    modules = {
        _module_name(path, package_root, package): path for path in trees
    }
    edges = {
        module: _imports(trees[path], module, package, set(modules))
        for module, path in modules.items()
    }
    inbound = Counter(target for targets in edges.values() for target in targets)
    outbound = {module: len(targets) for module, targets in edges.items()}
    clones: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    blocks: list[dict[str, Any]] = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                size = sum(1 for _ in ast.walk(node))
                if size >= 10:
                    record = {"name": node.name, "file": relative[path], "line": node.lineno, "size": size}
                    clones[_normalized_hash(node)].append(record)
                blocks.append({"name": node.name, "file": relative[path], "line": node.lineno, "complexity": _complexity(node)})
    duplicate_groups = [group for group in clones.values() if len(group) > 1]
    blocks.sort(key=lambda item: item["complexity"], reverse=True)
    module_rows = []
    for module in sorted(edges):
        module_rows.append({"module": module, "file": relative[modules[module]], "fan_in": inbound[module], "fan_out": outbound[module], "imports": sorted(edges[module])})
    candidates = [
        {"module": row["module"], "reason": "high fan-out", "fan_out": row["fan_out"]}
        for row in sorted(module_rows, key=lambda item: item["fan_out"], reverse=True)
        if row["fan_out"] > 1
    ]
    return {
        "scope": str(scope_path),
        "package": package,
        "python_files": len(files),
        "parse_errors": parse_errors,
        "modules": module_rows,
        "cycles": _cycles(edges),
        "complexity": blocks[:20],
        "duplicate_groups": duplicate_groups,
        "unused_functions": _unused_functions(trees, relative),
        "move_candidates": candidates[:20],
    }


def _cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    for start in sorted(edges):
        queue: deque[tuple[str, list[str]]] = deque([(start, [start])])
        while queue:
            current, path = queue.popleft()
            for target in sorted(edges[current]):
                if target == start and len(path) > 1:
                    cycle = sorted(path)
                    if cycle not in cycles:
                        cycles.append(cycle)
                elif target not in path and len(path) < len(edges):
                    queue.append((target, [*path, target]))
    return cycles


def render_quality_report(payload: dict[str, Any]) -> str:
    lines = [f"# Refactor Quality Report: `{payload['package']}`", "", f"Scope: `{payload['scope']}`", ""]
    lines += ["## Move Candidates", ""]
    lines += [f"- `{row['module']}`: {row['reason']} ({row['fan_out']})" for row in payload["move_candidates"]] or ["- None"]
    lines += ["", "## Module Dependencies", "", "| Module | Fan-in | Fan-out | Imports |", "|---|---:|---:|---|"]
    lines += [f"| `{row['module']}` | {row['fan_in']} | {row['fan_out']} | {', '.join(f'`{item}`' for item in row['imports']) or '-'} |" for row in payload["modules"]]
    lines += ["", "## Cycles", ""] + [f"- {' -> '.join(row)}" for row in payload["cycles"]] or ["- None"]
    lines += ["", "## Complexity Hotspots", ""] + [f"- `{row['file']}:{row['line']}` `{row['name']}`: {row['complexity']}" for row in payload["complexity"][:10]]
    lines += ["", "## Duplicates", ""]
    if payload["duplicate_groups"]:
        for group in payload["duplicate_groups"]:
            locations = ", ".join(
                f"`{item['file']}:{item['line']} {item['name']}`" for item in group
            )
            lines.append(f"- {locations}")
    else:
        lines.append("- None")
    lines += ["", "## Unused Functions", ""] + [f"- `{item['file']}:{item['line']}` `{item['name']}`" for item in payload["unused_functions"]] or ["- None"]
    return "\n".join(lines) + "\n"


def write_quality_report(*, project_root: Path, scope_path: Path, json_path: Path, markdown_path: Path) -> dict[str, Any]:
    payload = collect_quality_report(project_root=project_root, scope_path=scope_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_quality_report(payload), encoding="utf-8")
    return payload