#!/usr/bin/env python3
"""Project-agnostic structural refactoring tool.

Workflow:
1) tree          -- scan project -> .refactor/tree.yaml
2) apply-tree-patch -- apply a .yaml unified diff patch -> code changes -> verify
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import libcst as cst

from refactor_cli.discovery import (
    discover_python_files,
    generate_tree_payload,
    is_import_statement,
    load_config,
    load_module,
    print_tree,
    render_statements,
    resolve_project_root,
    statement_name,
)
from refactor_cli.architecture_report import collect_architecture_report
from refactor_cli.candidate_tools import resolve_cbm_binary
from refactor_cli.dependency_graph import collect_dependency_graph
from refactor_cli.file_io import (
    archive_patch,
    load_json,
    load_yaml,
    write_json,
)
from refactor_cli.runtime_tools import (
    _run_ruff_fix_imports,
    ensure_runtime_dependencies,
    resolve_emend_runner,
    run_formatter_on_file,
)
from refactor_cli.semantic_retrieval import collect_semantic_retrieval
from refactor_cli.safeguards import post_apply_safeguards
from refactor_cli.source_index import run_coderag_validate_only, run_source_index
from refactor_cli.tree_codec import (
    load_tree_yaml,
    write_tree_yaml,
)


DEFAULT_CONFIG = Path(".refactor/config.json")
DEFAULT_TREE = Path(".refactor/tree.yaml")
DEFAULT_TREE_PATCH = Path(".refactor/patches/latest.tree.patch.yaml")
DEFAULT_TREE_EDIT = Path(".refactor/patches/latest.tree.edit.yaml")
DEFAULT_APPLIED_PATCHES_DIR = Path(".refactor/patches/applied")
DEFAULT_CANDIDATE_OUTPUT_DIR = Path(".refactor/analysis/candidates")


# --- compact tree serialization -----------------------------------------------
# Format: files is a dict {path: [nodes]}
# Each node is either a plain string  "Kind name"  (leaf)
# or a one-key dict  {"Kind name": [children]}  (with members).


def split_nodes_by_symbol(
    module: cst.Module, symbols: set[str]
) -> tuple[list[cst.BaseStatement], list[cst.BaseStatement]]:
    moved_nodes: list[cst.BaseStatement] = []
    kept_nodes: list[cst.BaseStatement] = []
    for statement in module.body:
        name = statement_name(statement)
        if name in symbols:
            moved_nodes.append(statement)
        else:
            kept_nodes.append(statement)
    return moved_nodes, kept_nodes


def build_target_module(
    module: cst.Module, moved_nodes: list[cst.BaseStatement], operation: dict
) -> str:
    prelude = operation.get("target_prelude", [])
    prelude_text = "\n".join(prelude).rstrip()
    body = render_statements(module, moved_nodes).rstrip()
    if prelude_text:
        return f"{prelude_text}\n\n{body}\n"
    return f"{body}\n"


def build_updated_source(
    module: cst.Module, kept_nodes: list[cst.BaseStatement], import_block: str | None
) -> str:
    future_nodes = [
        stmt
        for stmt in kept_nodes
        if module.code_for_node(stmt).startswith("from __future__ import ")
    ]
    import_nodes = [
        stmt
        for stmt in kept_nodes
        if is_import_statement(stmt) and stmt not in future_nodes
    ]
    other_nodes = [
        stmt
        for stmt in kept_nodes
        if stmt not in future_nodes and stmt not in import_nodes
    ]

    chunks: list[str] = []
    if future_nodes:
        chunks.append(render_statements(module, future_nodes, separator="\n").rstrip())
    if import_nodes:
        chunks.append(render_statements(module, import_nodes, separator="\n").rstrip())
    if import_block:
        chunks.append(import_block.rstrip())
    if other_nodes:
        chunks.append(render_statements(module, other_nodes).rstrip())
    return "\n\n".join(chunk for chunk in chunks if chunk).rstrip() + "\n"


def choose_operation(
    config: dict, operation_name: str | None, intent_path: Path
) -> tuple[str, dict]:
    operations = config.get("operations", {})

    if operation_name:
        if operation_name not in operations:
            raise ValueError(
                f"Unknown operation '{operation_name}'. Available: {', '.join(sorted(operations))}"
            )
        return operation_name, operations[operation_name]

    if intent_path.exists():
        intent = load_json(intent_path)
        op = intent.get("operation")
        if op and op in operations:
            return op, operations[op]

    default_op = config.get("default_operation")
    if default_op:
        if default_op not in operations:
            raise ValueError(
                f"default_operation '{default_op}' not found in operations"
            )
        return default_op, operations[default_op]

    if len(operations) == 1:
        name = next(iter(operations.keys()))
        return name, operations[name]

    raise ValueError(
        "Could not resolve an operation. Set 'default_operation' in config or provide --operation."
    )


def extract_paths_from_tree_patch(patch_text: str) -> tuple[str, str]:
    old_path = ""
    new_path = ""
    for line in patch_text.splitlines():
        if line.startswith("--- "):
            old_path = line[4:].strip().split("\t", 1)[0]
        elif line.startswith("+++ "):
            new_path = line[4:].strip().split("\t", 1)[0]
        if old_path and new_path:
            break
    if not old_path or not new_path:
        raise ValueError("Tree patch must contain --- and +++ headers")
    return old_path, new_path


def apply_unified_diff_to_text(original: str, patch_text: str) -> str:
    def apply_by_chunk_replace(text: str, patch_lines_local: list[str]) -> str:
        current = text
        idx_local = 0
        while idx_local < len(patch_lines_local):
            if not patch_lines_local[idx_local].startswith("@@"):
                idx_local += 1
                continue
            idx_local += 1
            old_parts: list[str] = []
            new_parts: list[str] = []
            while idx_local < len(patch_lines_local) and not patch_lines_local[
                idx_local
            ].startswith("@@"):
                hline = patch_lines_local[idx_local]
                if hline.startswith(" "):
                    old_parts.append(hline[1:] + "\n")
                    new_parts.append(hline[1:] + "\n")
                elif hline.startswith("-"):
                    old_parts.append(hline[1:] + "\n")
                elif hline.startswith("+"):
                    new_parts.append(hline[1:] + "\n")
                elif hline.startswith("\\ No newline"):
                    pass
                else:
                    raise ValueError(f"Unsupported patch line: {hline}")
                idx_local += 1

            old_chunk = "".join(old_parts)
            new_chunk = "".join(new_parts)
            if old_chunk not in current:
                raise ValueError("Patch hunk context not found in source text")
            current = current.replace(old_chunk, new_chunk, 1)
        return current

    lines = original.splitlines(keepends=True)
    patch_lines = patch_text.splitlines()

    # Skip file headers
    idx = 0
    while idx < len(patch_lines) and not patch_lines[idx].startswith("@@"):
        idx += 1

    out: list[str] = []
    src_pos = 0

    while idx < len(patch_lines):
        header = patch_lines[idx]
        if not header.startswith("@@"):
            idx += 1
            continue

        header_body = header.split("@@")[1].strip()
        old_range = header_body.split(" ")[0]
        old_start_text = old_range.split(",")[0].lstrip("-")
        try:
            old_start = int(old_start_text)
        except ValueError:
            return apply_by_chunk_replace(original, patch_lines)

        # Copy untouched lines before hunk
        while src_pos < old_start - 1 and src_pos < len(lines):
            out.append(lines[src_pos])
            src_pos += 1

        idx += 1
        while idx < len(patch_lines) and not patch_lines[idx].startswith("@@"):
            hline = patch_lines[idx]
            if hline.startswith(" "):
                if src_pos >= len(lines):
                    raise ValueError("Patch context exceeds source length")
                out.append(lines[src_pos])
                src_pos += 1
            elif hline.startswith("-"):
                if src_pos >= len(lines):
                    raise ValueError("Patch removal exceeds source length")
                src_pos += 1
            elif hline.startswith("+"):
                out.append(hline[1:] + "\n")
            elif hline.startswith("\\ No newline"):
                pass
            else:
                raise ValueError(f"Unsupported patch line: {hline}")
            idx += 1

    # Copy remaining lines
    while src_pos < len(lines):
        out.append(lines[src_pos])
        src_pos += 1

    return "".join(out)


def build_symbol_index(tree_doc: dict) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for entry in tree_doc.get("files", []):
        index[entry.get("path", "")] = [
            node.get("name", "") for node in entry.get("nodes", [])
        ]
    return index


def tree_entry_map(tree_doc: dict) -> dict[str, dict]:
    return {entry.get("path", ""): entry for entry in tree_doc.get("files", [])}


def choose_move_from_trees(
    before_tree: dict, after_tree: dict
) -> tuple[str, str, list[str]]:
    before = build_symbol_index(before_tree)
    after = build_symbol_index(after_tree)

    removed_by_file: dict[str, set[str]] = {}
    added_by_file: dict[str, set[str]] = {}

    all_files = set(before.keys()) | set(after.keys())
    for file_path in all_files:
        bset = set(before.get(file_path, []))
        aset = set(after.get(file_path, []))
        removed = bset - aset
        added = aset - bset
        if removed:
            removed_by_file[file_path] = removed
        if added:
            added_by_file[file_path] = added

    if not removed_by_file or not added_by_file:
        raise ValueError("Could not detect moved symbols from tree patch")

    source = max(removed_by_file, key=lambda key: len(removed_by_file[key]))
    target = max(added_by_file, key=lambda key: len(added_by_file[key]))

    moved = removed_by_file[source].intersection(added_by_file[target])
    if not moved:
        raise ValueError("Detected source/target but no overlapping moved symbols")

    # Preserve source order for deterministic patch application
    ordered_source = before.get(source, [])
    ordered_symbols = [name for name in ordered_source if name in moved]
    return source, target, ordered_symbols


def build_operation_from_tree_delta(
    source: str, target: str, symbols: list[str]
) -> dict:
    return {
        "name": "tree_patch_delta",
        "type": "extract_top_level_symbols",
        "source": source,
        "target": target,
        "symbols": symbols,
        "source_import_block": None,
        "target_prelude": [],
    }


def apply_operation_to_tree_doc(tree_doc: dict, operation: dict) -> dict:
    source = operation["source"]
    target = operation["target"]
    symbols = set(operation["symbols"])

    new_doc = json.loads(json.dumps(tree_doc))
    entries = new_doc.get("files", [])
    entry_by_path = {entry.get("path", ""): entry for entry in entries}

    if source not in entry_by_path:
        raise ValueError(f"Source file '{source}' not present in tree")

    source_nodes = entry_by_path[source].get("nodes", [])
    moved_nodes = [node for node in source_nodes if node.get("name") in symbols]
    entry_by_path[source]["nodes"] = [
        node for node in source_nodes if node.get("name") not in symbols
    ]

    if target not in entry_by_path:
        target_entry = {"path": target, "nodes": []}
        insert_at = entries.index(entry_by_path[source]) + 1
        entries.insert(insert_at, target_entry)
        entry_by_path[target] = target_entry

    target_nodes = entry_by_path[target].get("nodes", [])
    existing = {node.get("name") for node in target_nodes}
    for node in moved_nodes:
        if node.get("name") not in existing:
            target_nodes.append(node)
    entry_by_path[target]["nodes"] = target_nodes
    return new_doc


def verify_moved_symbols(
    tree_doc: dict, source: str, target: str, symbols: list[str]
) -> bool:
    paths = tree_entry_map(tree_doc)
    source_nodes = {node.get("name") for node in paths.get(source, {}).get("nodes", [])}
    target_nodes = {node.get("name") for node in paths.get(target, {}).get("nodes", [])}
    required = set(symbols)
    return required.isdisjoint(source_nodes) and required.issubset(target_nodes)


def tree_docs_differ(before_tree: dict, after_tree: dict) -> bool:
    return json.dumps(before_tree, sort_keys=True) != json.dumps(
        after_tree, sort_keys=True
    )


def build_after_tree_from_edit(before_tree: dict, edit_doc: dict) -> dict:
    """Build the target tree from a simple YAML edit document.

    Format:
      version: 1
      moves:
        - source: main.py
          target: src/mobiliti/api/parsers.py
          symbols: [parse_status, parse_metadata]
      delete_files:
        - path/to/file.py
    """
    after_tree = json.loads(json.dumps(before_tree))

    for move in edit_doc.get("moves", []):
        source = move.get("source")
        target = move.get("target")
        symbols = move.get("symbols", [])
        if not source or not target or not symbols:
            raise ValueError("Each move requires source, target, and non-empty symbols")
        operation = build_operation_from_tree_delta(source, target, symbols)
        after_tree = apply_operation_to_tree_doc(after_tree, operation)

    delete_files = edit_doc.get("delete_files", [])
    if delete_files:
        delete_set = set(delete_files)
        after_tree["files"] = [
            entry
            for entry in after_tree.get("files", [])
            if entry.get("path") not in delete_set
        ]

    return after_tree


def run_tree_transition(
    *,
    root: Path,
    config_path: Path,
    tree_path: Path,
    before_tree: dict,
    after_tree: dict,
    move_backend: str,
) -> None:
    """Apply code changes from before/after tree delta and verify results."""
    tree_changed = tree_docs_differ(before_tree, after_tree)

    # Apply file deletions detected from tree diff
    deleted_files = detect_file_deletions_from_trees(before_tree, after_tree)
    for rel_path in deleted_files:
        target_file = root / rel_path
        if target_file.exists():
            target_file.unlink()
            print(f"DELETED {target_file}")

    # Apply symbol moves detected from tree diff (if any)
    before_symbols = build_symbol_index(before_tree)
    after_symbols = build_symbol_index(after_tree)
    has_symbol_moves = any(
        set(before_symbols.get(p, [])) != set(after_symbols.get(p, []))
        for p in set(before_symbols) | set(after_symbols)
        if p not in deleted_files
    )

    # Safety guard: fail fast on structural deltas this tool cannot apply yet.
    if tree_changed and not deleted_files and not has_symbol_moves:
        raise ValueError(
            "Unsupported tree delta: patch changed structure but no file deletion or symbol move "
            "was detected."
        )

    applied_move: tuple[str, str, list[str]] | None = None
    affected_files: list[str] = []
    if has_symbol_moves:
        source, target, symbols = choose_move_from_trees(before_tree, after_tree)
        operation = build_operation_from_tree_delta(source, target, symbols)
        if move_backend == "emend":
            apply_extract_top_level_symbols_emend(root, operation)
        else:
            apply_extract_top_level_symbols(root, operation)
        applied_move = (source, target, symbols)
        affected_files.extend([source, target])

    # Safety guard: auto-format + autoimport + compile-check + lint on changed files.
    lint_issues = post_apply_safeguards(root, affected_files)

    # Update tree file to match project state
    updated_tree = generate_tree_payload(config_path)
    write_tree_yaml(tree_path, updated_tree)

    # Verify: deleted files must be absent from updated tree
    updated_paths = {entry.get("path", "") for entry in updated_tree.get("files", [])}
    still_present = [p for p in deleted_files if p in updated_paths]
    if still_present:
        raise ValueError(
            f"Verification failed: expected deleted files still in tree: {still_present}"
        )

    # Safety guard: validate that moved symbols ended up in the expected target.
    if applied_move is not None:
        source, target, symbols = applied_move
        if not verify_moved_symbols(updated_tree, source, target, symbols):
            raise ValueError(
                "Verification failed: moved symbols are not in expected source/target after apply"
            )

    # Report lint issues at the end (non-fatal)
    if lint_issues and any(lint_issues.values()):
        print("\nLINT ISSUES DETECTED (non-fatal)")
        for rel_path in sorted(lint_issues.keys()):
            undefined = [
                line for line in lint_issues[rel_path] if "Undefined name" in line
            ]
            if undefined:
                names = set()
                for line in undefined:
                    if "`" in line:
                        names.add(line.split("`")[1])
                if names:
                    sorted_names = sorted(names)
                    print(
                        f"\n  {rel_path} needs imports for: {', '.join(sorted_names)}"
                    )
                    print(
                        f"    Suggestion: from src.mobiliti.api.models import {', '.join(sorted_names)}"
                    )
        print("\n  Run 'ruff check --fix' or manually add imports to resolve.\n")


def detect_file_deletions_from_trees(before_tree: dict, after_tree: dict) -> list[str]:
    before_paths = {entry.get("path", "") for entry in before_tree.get("files", [])}
    after_paths = {entry.get("path", "") for entry in after_tree.get("files", [])}
    return sorted(before_paths - after_paths)


def apply_extract_top_level_symbols(root: Path, operation: dict) -> None:
    source_path = root / operation["source"]
    target_path = root / operation["target"]
    symbols = set(operation["symbols"])

    module = load_module(source_path)
    moved_nodes, kept_nodes = split_nodes_by_symbol(module, symbols)
    if not moved_nodes:
        raise ValueError(f"No matching symbols found in {operation['source']}")

    target_content = build_target_module(module, moved_nodes, operation)
    source_content = build_updated_source(
        module, kept_nodes, operation.get("source_import_block")
    )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(target_content, encoding="utf-8")
    source_path.write_text(source_content, encoding="utf-8")

    print(f"APPLIED {operation.get('name', '<unnamed>')}")
    print(f"  source updated: {source_path}")
    print(f"  target written: {target_path}")
    print(f"  moved symbols: {len(moved_nodes)}")


def _strip_self_imports(file_path: Path) -> None:
    """Remove any import lines that import from the file's own module.

    Emend sometimes inserts `from <module> import X` and TYPE_CHECKING stubs
    where X is defined in the same file. Those produce circular import errors
    at runtime and must be removed.
    """
    module_path = file_path
    # Derive the dotted module name from path (best-effort from src/ layout)
    try:
        rel = module_path.relative_to(module_path.parents[0])
    except ValueError:
        rel = module_path

    # Build a canonical import prefix to match against
    module_stem = module_path.stem  # e.g. "models"
    # Derive full dotted name from path: src/mobiliti/api/models.py -> mobiliti.api.models
    parts = []
    p = module_path
    while p.name not in ("", "src"):
        parts.append(p.stem if p == module_path else p.name)
        p = p.parent
    parts.reverse()
    # Drop first element if it's the stem itself (single file)
    module_dotted = ".".join(parts)  # e.g. "mobiliti.api.models"

    original = module_path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    filtered: list[str] = []
    skip_block = False
    for line in lines:
        stripped = line.strip()
        # Remove: from <own_module> import ...
        if stripped.startswith(f"from {module_dotted} import"):
            skip_block = stripped.endswith("(")
            continue
        # Remove: continuation lines inside a skipped block
        if skip_block:
            if stripped.endswith(")"):
                skip_block = False
            continue
        # Remove: TYPE_CHECKING block importing from main/source file
        # (heuristic: if the only content is `from main import ...`)
        if stripped in ("if TYPE_CHECKING:", "if typing.TYPE_CHECKING:"):
            skip_block = True
            continue
        filtered.append(line)

    result = "".join(filtered)
    if result != original:
        module_path.write_text(result, encoding="utf-8")


def apply_extract_top_level_symbols_emend(root: Path, operation: dict) -> None:
    """Apply symbol moves via Emend (import-aware) instead of internal CST logic."""
    source = operation["source"]
    target = operation["target"]
    symbols = operation["symbols"]
    target_path = root / target
    emend_runner = resolve_emend_runner()
    if emend_runner is None:
        raise RuntimeError(
            "Emend backend requested but no emend runner found (uvx, emend CLI, or python -m emend)."
        )

    moved = 0
    for symbol in symbols:
        selector = f"{source}::{symbol}"
        cmd = [
            *emend_runner,
            "edit",
            "mv",
            selector,
            target,
            "-p",
            str(root),
            "--apply",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(
                f"Emend move failed for {selector} -> {target}: {detail}"
            )
        moved += 1
        print(f"  moved: {symbol}")

    # Post-move cleanup: remove circular self-imports Emend may have injected
    if target_path.exists():
        _strip_self_imports(target_path)

    # Merge fragmented per-symbol imports into consolidated blocks
    source_path = root / source
    for path in (source_path, target_path):
        if path.exists():
            _run_ruff_fix_imports(path)

    print(f"APPLIED {operation.get('name', '<unnamed>')} (backend=emend)")
    print(f"  source updated: {source_path}")
    print(f"  target written: {target_path}")
    print(f"  moved symbols: {moved}")


def cmd_init(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    if config_path.exists() and not args.force:
        print(f"Config already exists: {config_path}")
        return 0

    template = {
        "project_root": "..",
        "python_files": {
            "include": ["main.py", "src/**/*.py", "tests/**/*.py", "tools/**/*.py"],
            "exclude": [".venv/**", "**/__pycache__/**", "build/**", "dist/**"],
        },
    }

    write_json(config_path, template)
    print(f"Created config: {config_path}")
    return 0


def cmd_files(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = load_config(config_path)
    root = resolve_project_root(config_path, config)
    files = discover_python_files(root, config)

    print(f"PROJECT ROOT: {root}")
    print(f"PYTHON FILES ({len(files)}):")
    for path in files:
        print(f"- {path.relative_to(root).as_posix()}")
    return 0


def cmd_tree(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    payload = generate_tree_payload(config_path)

    out = Path(args.output)
    write_tree_yaml(out, payload)

    print(f"TREE WRITTEN: {out}")
    print(f"  files: {len(payload['files'])}")
    if args.print:
        for entry in payload["files"]:
            print(f"\n[{entry['path']}] ({len(entry['nodes'])} top-level nodes)")
            print_tree(entry["nodes"])
    return 0


def cmd_format(args: argparse.Namespace) -> int:
    """Format all discovered Python files using ruff."""
    ensure_runtime_dependencies(require_emend=False)

    config_path = Path(args.config)
    config = load_config(config_path)
    root = resolve_project_root(config_path, config)
    files = discover_python_files(root, config)

    print(f"FORMATTING {len(files)} files:")
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            run_formatter_on_file(path)
            print(f"  ✓ {rel}")
        except subprocess.CalledProcessError as e:
            print(f"  ✗ {rel} (exit {e.returncode})")
            return 1

    print(f"FORMAT COMPLETE: {len(files)} files")
    return 0


def cmd_apply_tree_patch(args: argparse.Namespace) -> int:
    ensure_runtime_dependencies(require_emend=args.move_backend == "emend")

    config_path = Path(args.config)
    config = load_config(config_path)
    root = resolve_project_root(config_path, config)

    tree_path = Path(args.tree)
    patch_path = Path(args.tree_patch)

    if not tree_path.exists():
        raise FileNotFoundError(f"Missing tree file: {tree_path}")
    if not patch_path.exists():
        raise FileNotFoundError(f"Missing tree patch file: {patch_path}")

    applied_dir = Path(args.applied_patches_dir)
    original_tree_text = tree_path.read_text(encoding="utf-8")
    patch_text = patch_path.read_text(encoding="utf-8")
    if not patch_text.strip() or patch_text.lstrip().startswith("# no-op"):
        archived_noop: Path | None = None
        if patch_path.exists() and not args.keep_patch:
            archived_noop = archive_patch(patch_path, applied_dir)
        print("TREE PATCH APPLY COMPLETE")
        print("  no-op: tree patch contained no changes")
        print(f"  updated tree: {tree_path}")
        print("  verification: OK")
        if archived_noop:
            print(f"  patch archived: {archived_noop}")
        return 0

    old_path, new_path = extract_paths_from_tree_patch(patch_text)
    if old_path != new_path:
        raise ValueError("Tree patch must target a single tree file")

    temp_tree_text = apply_unified_diff_to_text(original_tree_text, patch_text)

    # Create temporary tree file artifact
    temp_handle = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".tree.tmp.yaml",
        prefix="refactor-",
        dir=str(tree_path.parent),
        delete=False,
    )
    temp_path = Path(temp_handle.name)
    temp_handle.write(temp_tree_text)
    temp_handle.close()

    try:
        before_tree = load_tree_yaml(tree_path)
        after_tree = load_tree_yaml(temp_path)
        run_tree_transition(
            root=root,
            config_path=config_path,
            tree_path=tree_path,
            before_tree=before_tree,
            after_tree=after_tree,
            move_backend=args.move_backend,
        )

    finally:
        # Always clean up temp file
        if temp_path.exists():
            temp_path.unlink()

    archived_patch: Path | None = None
    if patch_path.exists() and not args.keep_patch:
        archived_patch = archive_patch(patch_path, applied_dir)

    print("TREE PATCH APPLY COMPLETE")
    print(f"  applied patch: {patch_path}")
    print(f"  updated tree: {tree_path}")
    print("  verification: OK")
    if archived_patch:
        print(f"  patch archived: {archived_patch}")
    else:
        print("  patch kept (--keep-patch)")
    return 0


def cmd_apply_tree_edit(args: argparse.Namespace) -> int:
    ensure_runtime_dependencies(require_emend=args.move_backend == "emend")

    config_path = Path(args.config)
    config = load_config(config_path)
    root = resolve_project_root(config_path, config)

    tree_path = Path(args.tree)
    edit_path = Path(args.tree_edit)

    if not tree_path.exists():
        raise FileNotFoundError(f"Missing tree file: {tree_path}")
    if not edit_path.exists():
        raise FileNotFoundError(f"Missing tree edit file: {edit_path}")

    applied_dir = Path(args.applied_patches_dir)
    edit_doc = load_yaml(edit_path)
    if not edit_doc:
        archived_edit: Path | None = None
        if edit_path.exists() and not args.keep_patch:
            archived_edit = archive_patch(edit_path, applied_dir)
        print("TREE EDIT APPLY COMPLETE")
        print("  no-op: tree edit contained no changes")
        print(f"  updated tree: {tree_path}")
        print("  verification: OK")
        if archived_edit:
            print(f"  edit archived: {archived_edit}")
        return 0

    before_tree = load_tree_yaml(tree_path)
    after_tree = build_after_tree_from_edit(before_tree, edit_doc)

    run_tree_transition(
        root=root,
        config_path=config_path,
        tree_path=tree_path,
        before_tree=before_tree,
        after_tree=after_tree,
        move_backend=args.move_backend,
    )

    archived_edit: Path | None = None
    if edit_path.exists() and not args.keep_patch:
        archived_edit = archive_patch(edit_path, applied_dir)

    print("TREE EDIT APPLY COMPLETE")
    print(f"  applied edit: {edit_path}")
    print(f"  updated tree: {tree_path}")
    print("  verification: OK")
    if archived_edit:
        print(f"  edit archived: {archived_edit}")
    else:
        print("  edit kept (--keep-patch)")
    return 0


def cmd_candidate_phase_a(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    if not project_root.exists():
        raise FileNotFoundError(f"Project root not found: {project_root}")

    cbm_binary = resolve_cbm_binary(args.cbm_binary)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_index = run_source_index(
        project_root=project_root,
        cbm_binary=cbm_binary,
        project_name=args.project_name,
        mode=args.index_mode,
    )
    write_json(output_dir / "source_index.json", source_index)
    if not source_index.get("ok"):
        print("CANDIDATE PHASE A FAILED at source_index")
        print(f"  details: {output_dir / 'source_index.json'}")
        return 1

    project_name = source_index["project_name"]

    dependency = collect_dependency_graph(
        cbm_binary=cbm_binary,
        project_root=project_root,
        project_name=project_name,
        max_rows=args.max_rows,
    )
    write_json(output_dir / "dependency_graph.json", dependency)

    terms = [term.strip() for term in args.semantic_terms.split(",") if term.strip()]
    semantic = collect_semantic_retrieval(
        cbm_binary=cbm_binary,
        project_root=project_root,
        project_name=project_name,
        semantic_terms=terms,
        limit=args.semantic_limit,
    )
    write_json(output_dir / "semantic_retrieval.json", semantic)

    architecture = collect_architecture_report(
        cbm_binary=cbm_binary,
        project_root=project_root,
        project_name=project_name,
        aspects=["overview"],
    )
    write_json(output_dir / "architecture_report.json", architecture)

    coderag_result = None
    if args.include_coderag_validate:
        coderag_path = Path(args.coderag_path)
        if coderag_path.exists():
            coderag_result = run_coderag_validate_only(
                coderag_root=coderag_path,
                project_root=project_root,
            )
            write_json(output_dir / "coderag_validate.json", coderag_result)
        else:
            coderag_result = {
                "provider": "CodeRAG",
                "ok": False,
                "error": f"CodeRAG path not found: {coderag_path}",
            }
            write_json(output_dir / "coderag_validate.json", coderag_result)

    summary = {
        "project_root": str(project_root),
        "project_name": project_name,
        "cbm_binary": str(cbm_binary),
        "output_dir": str(output_dir),
        "modules": {
            "source_index": source_index.get("ok", False),
            "dependency_graph": dependency.get("ok", False),
            "semantic_retrieval": semantic.get("ok", False),
            "architecture_report": architecture.get("ok", False),
            "coderag_validate": None
            if coderag_result is None
            else coderag_result.get("ok", False),
        },
    }
    write_json(output_dir / "summary.json", summary)

    print("CANDIDATE PHASE A COMPLETE")
    print(f"  project: {project_name}")
    print(f"  output: {output_dir}")
    for key, ok in summary["modules"].items():
        if ok is None:
            print(f"  - {key}: SKIP")
            continue
        marker = "OK" if ok else "FAIL"
        print(f"  - {key}: {marker}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project-agnostic structural refactoring tool"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="Create default .refactor/config.json"
    )
    init_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=cmd_init)

    files_parser = subparsers.add_parser(
        "files", help="List relevant Python files from config"
    )
    files_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    files_parser.set_defaults(func=cmd_files)

    tree_parser = subparsers.add_parser(
        "tree", help="Generate and persist project structural tree"
    )
    tree_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    tree_parser.add_argument("--output", default=str(DEFAULT_TREE))
    tree_parser.add_argument("--print", action="store_true")
    tree_parser.set_defaults(func=cmd_tree)

    format_parser = subparsers.add_parser(
        "format", help="Format all discovered Python files using ruff"
    )
    format_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    format_parser.set_defaults(func=cmd_format)

    apply_tree_patch_parser = subparsers.add_parser(
        "apply-tree-patch",
        help="Apply a tree diff patch end-to-end (temp tree, internal change request, apply, verify, cleanup)",
    )
    apply_tree_patch_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    apply_tree_patch_parser.add_argument("--tree", default=str(DEFAULT_TREE))
    apply_tree_patch_parser.add_argument(
        "--tree-patch", default=str(DEFAULT_TREE_PATCH)
    )
    apply_tree_patch_parser.add_argument("--keep-patch", action="store_true")
    apply_tree_patch_parser.add_argument(
        "--applied-patches-dir", default=str(DEFAULT_APPLIED_PATCHES_DIR)
    )
    apply_tree_patch_parser.add_argument(
        "--move-backend",
        choices=["internal", "emend"],
        default="emend",
        help="Backend used for symbol moves detected from the tree patch",
    )
    apply_tree_patch_parser.set_defaults(func=cmd_apply_tree_patch)

    apply_tree_edit_parser = subparsers.add_parser(
        "apply-tree-edit",
        help="Apply a line-number-free tree edit YAML (moves/delete_files) and reuse the same transition workflow",
    )
    apply_tree_edit_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    apply_tree_edit_parser.add_argument("--tree", default=str(DEFAULT_TREE))
    apply_tree_edit_parser.add_argument("--tree-edit", default=str(DEFAULT_TREE_EDIT))
    apply_tree_edit_parser.add_argument("--keep-patch", action="store_true")
    apply_tree_edit_parser.add_argument(
        "--applied-patches-dir", default=str(DEFAULT_APPLIED_PATCHES_DIR)
    )
    apply_tree_edit_parser.add_argument(
        "--move-backend",
        choices=["internal", "emend"],
        default="emend",
        help="Backend used for symbol moves detected from the tree edit",
    )
    apply_tree_edit_parser.set_defaults(func=cmd_apply_tree_edit)

    phase_a_parser = subparsers.add_parser(
        "candidate-phase-a",
        help="Run adapter-based candidate analysis modules and write normalized artifacts",
    )
    phase_a_parser.add_argument("--project-root", default=".")
    phase_a_parser.add_argument("--project-name", default=None)
    phase_a_parser.add_argument("--cbm-binary", default=None)
    phase_a_parser.add_argument("--index-mode", default="moderate")
    phase_a_parser.add_argument("--max-rows", type=int, default=5000)
    phase_a_parser.add_argument(
        "--semantic-terms",
        default="dependency,refactor,module,call graph",
    )
    phase_a_parser.add_argument("--semantic-limit", type=int, default=100)
    phase_a_parser.add_argument(
        "--include-coderag-validate",
        action="store_true",
    )
    phase_a_parser.add_argument(
        "--coderag-path",
        default=".eval/candidates/coderag",
    )
    phase_a_parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_CANDIDATE_OUTPUT_DIR),
    )
    phase_a_parser.set_defaults(func=cmd_candidate_phase_a)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
