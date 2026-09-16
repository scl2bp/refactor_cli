from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


def _module_name(path: Path, project_root: Path, scope_path: Path) -> str:
    relative = path.relative_to(project_root)
    parts = list(relative.with_suffix("").parts)
    if parts and parts[0] in {"src", "lib"}:
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_relative(module: str, level: int, name: str | None) -> str:
    anchor = module.split(".")[:-1]
    if level > 1:
        anchor = anchor[: max(0, len(anchor) - level + 1)]
    return ".".join((*anchor, *(name.split(".") if name else ())))


def _import_names(tree: ast.AST, module: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = (
                _resolve_relative(module, node.level, node.module)
                if node.level
                else (node.module or "")
            )
            if base:
                names.add(base)
                names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def collect_scope_baseline(
    *, project_root: Path, scope_path: Path, files: list[Path]
) -> dict[str, Any]:
    project_root = project_root.resolve()
    scope_path = scope_path.resolve()
    configured_files = sorted(path.resolve() for path in files)
    module_by_file = {
        path: _module_name(path, project_root, scope_path) for path in configured_files
    }
    known_modules = set(module_by_file.values())
    parsed_files: list[str] = []
    parse_errors: list[dict[str, str]] = []
    imports: dict[str, set[str]] = {}
    external_imports: dict[str, set[str]] = {}

    for path in configured_files:
        relative = path.relative_to(project_root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as error:
            parse_errors.append({"file": relative, "error": str(error)})
            continue
        module = module_by_file[path]
        parsed_files.append(relative)
        internal: set[str] = set()
        external: set[str] = set()
        for imported in _import_names(tree, module):
            candidates = [imported]
            while candidates[-1] and candidates[-1] not in known_modules:
                candidates.append(candidates[-1].rpartition(".")[0])
            target = next((candidate for candidate in candidates if candidate in known_modules), None)
            if target and target != module:
                internal.add(target)
            elif imported:
                external.add(imported.split(".", 1)[0])
        imports[module] = internal
        external_imports[module] = external

    internal_edges = [
        {"source": source, "relation": "IMPORTS", "target": target}
        for source in sorted(imports)
        for target in sorted(imports[source])
    ]
    external_rows = [
        {"source": source, "import": imported}
        for source in sorted(external_imports)
        for imported in sorted(external_imports[source])
    ]
    return {
        "provider": "python-ast",
        "project_root": str(project_root),
        "scope_path": str(scope_path.relative_to(project_root).as_posix()),
        "configured_files": [path.relative_to(project_root).as_posix() for path in configured_files],
        "parsed_files": sorted(parsed_files),
        "parse_errors": parse_errors,
        "modules": [
            {"module": module, "file": path.relative_to(project_root).as_posix()}
            for path, module in sorted(module_by_file.items(), key=lambda item: item[1])
            if path.relative_to(project_root).as_posix() in parsed_files
        ],
        "internal_import_edges": internal_edges,
        "external_imports": external_rows,
        "counts": {
            "configured_files": len(configured_files),
            "parsed_files": len(parsed_files),
            "parse_errors": len(parse_errors),
            "internal_import_edges": len(internal_edges),
            "external_imports": len(external_rows),
        },
    }