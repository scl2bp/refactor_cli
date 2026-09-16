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
from typing import Any

from refactor_cli.analysis.architecture_report import collect_architecture_report
from refactor_cli.candidate_report import build_candidate_report
from refactor_cli.analysis.candidate_tools import resolve_cbm_binary; from refactor_cli.analysis.candidate_tools import run_cbm_tool
from refactor_cli.analysis.dependency_graph import collect_dependency_graph
from refactor_cli.discovery import (
    discover_python_files,
    generate_tree_payload,
    load_config,
    print_tree,
    resolve_project_root,
)
from refactor_cli.file_io import (
    archive_patch,
    load_json,
    load_yaml,
    write_json,
)
from refactor_cli.runtime_tools import (
    ensure_runtime_dependencies,
    run_formatter_on_file,
)
from refactor_cli.analysis.semantic_retrieval import collect_semantic_retrieval
from refactor_cli.analysis.source_index import run_source_index; from refactor_cli.analysis.source_index import run_coderag_validate_only
from refactor_cli.analysis.quality_report import write_quality_report
from refactor_cli.transforms import (
    apply_unified_diff_to_text,
    build_after_tree_from_edit,
    run_tree_transition,
)
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
DEFAULT_CANDIDATE_REPORT = DEFAULT_CANDIDATE_OUTPUT_DIR / "report.md"


# --- compact tree serialization -----------------------------------------------
# Format: files is a dict {path: [nodes]}
# Each node is either a plain string  "Kind name"  (leaf)
# or a one-key dict  {"Kind name": [children]}  (with members).


def _load_optional_config(config_path: Path) -> dict[str, Any]:
    if config_path.exists():
        return load_config(config_path)
    return {}


def _candidate_analysis_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("candidate_analysis", {})
    return raw if isinstance(raw, dict) else {}


def _config_or_default(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str) and not value.strip():
        return fallback
    return value


def _resolve_path_setting(project_root: Path, value: str | None, default: Path) -> Path:
    raw = _config_or_default(value, str(default))
    path = Path(raw)
    if path.is_absolute():
        return path
    return (project_root / path).resolve()


def _resolve_optional_project_root(
    args_project_root: str | None, config_path: Path, config: dict[str, Any]
) -> Path:
    if args_project_root:
        return Path(args_project_root).resolve()
    if config:
        return resolve_project_root(config_path, config)
    return Path(".").resolve()


def _find_default_config_path(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        config_path = candidate / DEFAULT_CONFIG
        if config_path.exists():
            return config_path
    return DEFAULT_CONFIG.resolve()


def _semantic_terms_setting(value: str | list[str] | None) -> list[str]:
    if value is None:
        return ["dependency", "refactor", "module", "call graph"]
    if isinstance(value, list):
        return [str(term).strip() for term in value if str(term).strip()]
    return [term.strip() for term in value.split(",") if term.strip()]


def _exclude_substrings_setting(value: list[str] | None) -> list[str]:
    if value is None:
        return [".eval."]
    return [str(token).strip() for token in value if str(token).strip()]


def _semantic_query_profiles_setting(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        query = str(item.get("query", "")).strip()
        terms = item.get("semantic_terms")
        if not name:
            continue
        if not query and not (isinstance(terms, list) and terms):
            continue
        row: dict[str, Any] = {
            "name": name,
            "query": query,
            "why": str(item.get("why", "")).strip(),
        }
        scope_path = str(item.get("scope_path", "")).strip()
        if scope_path:
            row["scope_path"] = scope_path
        if isinstance(terms, list):
            row["semantic_terms"] = [
                str(token).strip() for token in terms if str(token).strip()
            ]
        out.append(row)
    return out


def _load_summary_if_present(input_dir: Path) -> dict[str, Any]:
    summary_path = input_dir / "summary.json"
    if summary_path.exists():
        return load_json(summary_path)
    return {}


def _resolve_candidate_phase_a_settings(args: argparse.Namespace) -> dict[str, Any]:
    config_path = Path(args.config)
    config = _load_optional_config(config_path)
    analysis = _candidate_analysis_config(config)

    project_root = _resolve_optional_project_root(
        args.project_root, config_path, config
    )
    scope_path = str(
        _config_or_default(args.scope_path, analysis.get("scope_path", ""))
    ).strip()
    scope_qn_prefix = str(
        _config_or_default(
            args.scope_qn_prefix,
            analysis.get("scope_qn_prefix") or scope_path.replace("/", "."),
        )
    ).strip()

    settings = {
        "config_path": config_path,
        "project_root": project_root,
        "project_name": _config_or_default(
            args.project_name, analysis.get("project_name")
        ),
        "cbm_binary": resolve_cbm_binary(
            _config_or_default(args.cbm_binary, analysis.get("cbm_binary"))
        ),
        "index_mode": str(
            _config_or_default(args.index_mode, analysis.get("index_mode", "moderate"))
        ),
        "max_rows": int(
            _config_or_default(args.max_rows, analysis.get("max_rows", 5000))
        ),
        "semantic_terms": _semantic_terms_setting(
            _config_or_default(args.semantic_terms, analysis.get("semantic_terms"))
        ),
        "semantic_limit": int(
            _config_or_default(args.semantic_limit, analysis.get("semantic_limit", 100))
        ),
        "scope_path": scope_path,
        "scope_qn_prefix": scope_qn_prefix,
        "exclude_qn_substrings": _exclude_substrings_setting(
            _config_or_default(
                args.exclude_qn_substring,
                analysis.get("exclude_qn_substrings"),
            )
        ),
        "include_coderag_validate": bool(
            _config_or_default(
                args.include_coderag_validate,
                analysis.get("include_coderag_validate", False),
            )
        ),
        "coderag_path": _resolve_path_setting(
            project_root,
            _config_or_default(args.coderag_path, analysis.get("coderag_path")),
            Path(".eval/candidates/coderag"),
        ),
        "output_dir": _resolve_path_setting(
            project_root,
            _config_or_default(args.output_dir, analysis.get("output_dir")),
            DEFAULT_CANDIDATE_OUTPUT_DIR,
        ),
        "semantic_query_profiles": _semantic_query_profiles_setting(
            analysis.get("semantic_query_profiles")
        ),
    }
    return settings


def _resolve_candidate_report_settings(args: argparse.Namespace) -> dict[str, Any]:
    config_path = Path(args.config)
    config = _load_optional_config(config_path)
    analysis = _candidate_analysis_config(config)

    project_root = _resolve_optional_project_root(
        args.project_root, config_path, config
    )
    input_dir = _resolve_path_setting(
        project_root,
        _config_or_default(args.input_dir, analysis.get("output_dir")),
        DEFAULT_CANDIDATE_OUTPUT_DIR,
    )
    summary = _load_summary_if_present(input_dir)
    summary_scope = (
        summary.get("scope", {}) if isinstance(summary.get("scope", {}), dict) else {}
    )

    scope_path = str(
        _config_or_default(
            args.scope_path,
            analysis.get("scope_path") or summary_scope.get("scope_path") or "",
        )
    ).strip()

    settings = {
        "config_path": config_path,
        "project_root": project_root,
        "input_dir": input_dir,
        "output_path": _resolve_path_setting(
            project_root,
            _config_or_default(args.output, analysis.get("report_output")),
            DEFAULT_CANDIDATE_REPORT,
        ),
        "scope_path": scope_path,
        "cbm_binary": _config_or_default(
            args.cbm_binary,
            analysis.get("cbm_binary") or summary.get("cbm_binary"),
        ),
        "include_demo_artifacts": bool(
            _config_or_default(
                args.include_demo_artifacts,
                analysis.get("include_demo_artifacts", False),
            )
        ),
        "semantic_query_profiles": _semantic_query_profiles_setting(
            analysis.get("semantic_query_profiles")
        ),
    }
    return settings


def _project_name_default(project_root: Path, configured: Any) -> str:
    if configured is None:
        return project_root.resolve().name
    text = str(configured).strip()
    return text or project_root.resolve().name


def _parse_semantic_query(value: str | None) -> list[str] | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                terms = [str(token).strip() for token in parsed if str(token).strip()]
                return terms or None
        except json.JSONDecodeError:
            pass
    terms = [token.strip() for token in raw.split(",") if token.strip()]
    return terms or None


def _parse_cbm_options(raw_options: str | None) -> dict[str, Any]:
    if raw_options is None or not raw_options.strip():
        return {}
    tokens = raw_options.strip().split()
    parsed: dict[str, Any] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("--"):
            raise ValueError(f"CBM options must start with --flag names; got '{token}'")
        key = token.lstrip("-").replace("-", "_")
        index += 1
        value: Any = True
        if index < len(tokens) and not tokens[index].startswith("--"):
            value = tokens[index]
            index += 1
        parsed[key] = value
    return parsed


def _profile_terms_setting(profile: dict[str, Any]) -> list[str]:
    terms = profile.get("semantic_terms")
    if isinstance(terms, list):
        out = [str(token).strip() for token in terms if str(token).strip()]
        if out:
            return out
    query = str(profile.get("query", "")).strip()
    return [token.strip() for token in query.split() if token.strip()]


def _resolve_candidate_search_settings(args: argparse.Namespace) -> dict[str, Any]:
    config_path = (
        Path(args.config)
        if getattr(args, "config", None)
        else _find_default_config_path()
    )
    config = _load_optional_config(config_path)
    analysis = _candidate_analysis_config(config)
    project_root = _resolve_optional_project_root(
        args.project_root, config_path, config
    )

    configured_profiles = _semantic_query_profiles_setting(
        analysis.get("semantic_query_profiles")
    )
    selected_profile: dict[str, Any] | None = None
    if args.profile:
        needle = args.profile.strip().lower()
        for profile in configured_profiles:
            if str(profile.get("name", "")).strip().lower() == needle:
                selected_profile = profile
                break
        if selected_profile is None:
            available = (
                ", ".join(p.get("name", "") for p in configured_profiles) or "none"
            )
            raise ValueError(
                f"Unknown semantic profile '{args.profile}'. Available profiles: {available}"
            )

    scope_path = str(
        _config_or_default(
            args.scope_path,
            (selected_profile or {}).get("scope_path")
            or analysis.get("scope_path", ""),
        )
    ).strip()
    scope_qn_prefix = str(
        _config_or_default(
            getattr(args, "scope_qn_prefix", None),
            analysis.get("scope_qn_prefix") or scope_path.replace("/", "."),
        )
    ).strip()

    explicit_terms = _parse_semantic_query(args.semantic_query)
    if explicit_terms is not None:
        semantic_terms = explicit_terms
    elif selected_profile is not None:
        semantic_terms = _profile_terms_setting(selected_profile)
    else:
        semantic_terms = _semantic_terms_setting(analysis.get("semantic_terms"))

    default_file_pattern = f"{scope_path}/*" if scope_path else None
    cbm_options = _parse_cbm_options(getattr(args, "cbm_options", None))

    return {
        "config_path": config_path,
        "project_root": project_root,
        "project_name": _project_name_default(
            project_root,
            _config_or_default(args.project_name, analysis.get("project_name")),
        ),
        "cbm_binary": resolve_cbm_binary(
            _config_or_default(args.cbm_binary, analysis.get("cbm_binary"))
        ),
        "semantic_query": semantic_terms,
        "scope_qn_prefix": scope_qn_prefix,
        "label": _config_or_default(args.label, None),
        "file_pattern": _config_or_default(args.file_pattern, default_file_pattern),
        "limit": int(
            _config_or_default(
                args.limit,
                analysis.get("semantic_limit", 100),
            )
        ),
        "format": str(_config_or_default(args.format, "json")),
        "profile": selected_profile,
        "cbm_options": cbm_options,
    }


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
        "candidate_analysis": {
            "project_name": None,
            "cbm_binary": None,
            "index_mode": "moderate",
            "max_rows": 5000,
            "semantic_terms": ["dependency", "refactor", "module", "call graph"],
            "semantic_limit": 100,
            "scope_path": "",
            "scope_qn_prefix": "",
            "exclude_qn_substrings": [".eval."],
            "include_coderag_validate": False,
            "coderag_path": ".eval/candidates/coderag",
            "output_dir": ".refactor/analysis/candidates",
            "report_output": ".refactor/analysis/candidates/report.md",
            "include_demo_artifacts": False,
            "semantic_query_profiles": [
                {
                    "name": "Input processing",
                    "query": "config load parse settings schema validation",
                    "why": "Locate where project input is loaded and normalized",
                    "scope_path": "",
                },
                {
                    "name": "Calculation and processing",
                    "query": "core algorithm simulation optimize compute run_model",
                    "why": "Identify the main calculation pipeline",
                    "scope_path": "",
                },
                {
                    "name": "Methodology",
                    "query": "assumption strategy workflow decision heuristic",
                    "why": "Find modules that explain process assumptions and methods",
                    "scope_path": "",
                },
                {
                    "name": "Report generation",
                    "query": "report export dashboard plot summary",
                    "why": "Find where user-facing results are built",
                    "scope_path": "",
                },
            ],
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
    moves = edit_doc.get("moves", [])
    if moves:
        for move in moves:
            staged_edit = {"version": edit_doc.get("version", 1), "moves": [move]}
            after_tree = build_after_tree_from_edit(before_tree, staged_edit)
            run_tree_transition(
                root=root,
                config_path=config_path,
                tree_path=tree_path,
                before_tree=before_tree,
                after_tree=after_tree,
                move_backend=args.move_backend,
            )
            before_tree = load_tree_yaml(tree_path)

        delete_edit = {
            "version": edit_doc.get("version", 1),
            "delete_files": edit_doc.get("delete_files", []),
        }
        if delete_edit["delete_files"]:
            after_tree = build_after_tree_from_edit(before_tree, delete_edit)
            run_tree_transition(
                root=root,
                config_path=config_path,
                tree_path=tree_path,
                before_tree=before_tree,
                after_tree=after_tree,
                move_backend=args.move_backend,
            )
    else:
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
    settings = _resolve_candidate_phase_a_settings(args)
    project_root = settings["project_root"]
    if not project_root.exists():
        raise FileNotFoundError(f"Project root not found: {project_root}")

    cbm_binary = settings["cbm_binary"]
    output_dir = settings["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    source_index = run_source_index(
        project_root=project_root,
        cbm_binary=cbm_binary,
        project_name=settings["project_name"],
        config_path=settings["config_path"],
        mode=settings["index_mode"],
    )
    write_json(output_dir / "source_index.json", source_index)
    if not source_index.get("ok"):
        print("CANDIDATE PHASE A FAILED at source_index")
        print(f"  details: {output_dir / 'source_index.json'}")
        return 1

    project_name = source_index["project_name"]
    scope_path = settings["scope_path"]
    scope_qn_prefix = settings["scope_qn_prefix"]
    exclude_qn_substrings = settings["exclude_qn_substrings"]

    dependency = collect_dependency_graph(
        cbm_binary=cbm_binary,
        project_root=project_root,
        project_name=project_name,
        max_rows=settings["max_rows"],
        scope_qn_prefix=scope_qn_prefix or None,
        exclude_qn_substrings=exclude_qn_substrings,
    )
    write_json(output_dir / "dependency_graph.json", dependency)

    terms = settings["semantic_terms"]
    semantic = collect_semantic_retrieval(
        cbm_binary=cbm_binary,
        project_root=project_root,
        project_name=project_name,
        semantic_terms=terms,
        limit=settings["semantic_limit"],
        file_pattern=f"{scope_path}/*" if scope_path else None,
    )
    write_json(output_dir / "semantic_retrieval.json", semantic)

    architecture = collect_architecture_report(
        cbm_binary=cbm_binary,
        project_root=project_root,
        project_name=project_name,
        aspects=["overview"],
        scope_path=scope_path or None,
    )
    write_json(output_dir / "architecture_report.json", architecture)

    coderag_result = None
    if settings["include_coderag_validate"]:
        coderag_path = settings["coderag_path"]
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
        "scope": {
            "scope_path": scope_path,
            "scope_qn_prefix": scope_qn_prefix,
            "exclude_qn_substrings": exclude_qn_substrings,
            "semantic_query_profiles": settings["semantic_query_profiles"],
            "daemon_mode": "out_of_scope",
        },
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


def cmd_candidate_report(args: argparse.Namespace) -> int:
    settings = _resolve_candidate_report_settings(args)
    input_dir = settings["input_dir"]
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    output_path = settings["output_path"]
    report = build_candidate_report(
        input_dir=input_dir,
        output_path=output_path,
        scope_path=settings["scope_path"],
        project_root=settings["project_root"],
        cbm_binary_path=settings["cbm_binary"],
        include_demo_artifacts=settings["include_demo_artifacts"],
        semantic_query_profiles=settings["semantic_query_profiles"],
    )

    print("CANDIDATE REPORT WRITTEN")
    print(f"  input: {input_dir}")
    print(f"  output: {output_path}")
    print(f"  lines: {len(report.splitlines())}")
    return 0


def cmd_candidate_search(args: argparse.Namespace) -> int:
    settings = _resolve_candidate_search_settings(args)
    flags: dict[str, Any] = {
        "project": settings["project_name"],
        "limit": settings["limit"],
        "format": settings["format"],
    }
    if settings["semantic_query"]:
        flags["semantic_query"] = settings["semantic_query"]
    if settings["label"]:
        flags["label"] = settings["label"]
    if settings["file_pattern"]:
        flags["file_pattern"] = settings["file_pattern"]
    flags.update(settings.get("cbm_options", {}))

    result = run_cbm_tool(
        settings["cbm_binary"],
        "search_graph",
        flags,
        cwd=settings["project_root"],
    )
    if not result.get("ok"):
        print("CANDIDATE SEARCH FAILED")
        print(f"  project: {settings['project_name']}")
        print(f"  command: {' '.join(result.get('command', []))}")
        if result.get("stderr"):
            print(result["stderr"].strip())
        return 1

    profile = settings.get("profile")
    if profile is not None:
        print(f"PROFILE: {profile.get('name', '')}")
    print("CANDIDATE SEARCH COMPLETE")
    print(f"  project: {settings['project_name']}")
    print(f"  scope: {settings.get('file_pattern') or 'none'}")
    print(f"  query: {settings['semantic_query']}")
    print(f"  label: {settings.get('label') or 'any'}")
    print(f"  limit: {settings['limit']}")
    print(json.dumps(result.get("payload", {}), ensure_ascii=True))
    return 0


def cmd_quality_report(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = _load_optional_config(config_path)
    analysis = _candidate_analysis_config(config)
    project_root = _resolve_optional_project_root(args.project_root, config_path, config)
    scope_value = _config_or_default(args.scope_path, analysis.get("scope_path", "src"))
    scope_path = Path(scope_value)
    if not scope_path.is_absolute():
        scope_path = (project_root / scope_path).resolve()
    output_dir = Path(args.output_dir or ".refactor/analysis/quality")
    if not output_dir.is_absolute():
        output_dir = (project_root / output_dir).resolve()
    payload = write_quality_report(
        project_root=project_root,
        scope_path=scope_path,
        json_path=output_dir / "quality.json",
        markdown_path=output_dir / "quality.md",
    )
    print("QUALITY REPORT WRITTEN")
    print(f"  scope: {scope_path}")
    print(f"  modules: {len(payload['modules'])}")
    print(f"  move candidates: {len(payload['move_candidates'])}")
    print(f"  duplicate groups: {len(payload['duplicate_groups'])}")
    print(f"  unused functions: {len(payload['unused_functions'])}")
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
    phase_a_parser.add_argument("--project-root", default=None)
    phase_a_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    phase_a_parser.add_argument("--project-name", default=None)
    phase_a_parser.add_argument("--cbm-binary", default=None)
    phase_a_parser.add_argument("--index-mode", default=None)
    phase_a_parser.add_argument("--max-rows", type=int, default=None)
    phase_a_parser.add_argument(
        "--semantic-terms",
        default=None,
    )
    phase_a_parser.add_argument("--semantic-limit", type=int, default=None)
    phase_a_parser.add_argument(
        "--scope-path",
        default=None,
        help="File path scope used for semantic and architecture queries",
    )
    phase_a_parser.add_argument(
        "--scope-qn-prefix",
        default=None,
        help="Qualified-name prefix used to scope dependency edge extraction",
    )
    phase_a_parser.add_argument(
        "--exclude-qn-substring",
        action="append",
        default=None,
        help="Substring filter applied to dependency source/target qualified names (repeatable)",
    )
    phase_a_parser.add_argument(
        "--include-coderag-validate",
        action="store_true",
        default=None,
    )
    phase_a_parser.add_argument(
        "--coderag-path",
        default=None,
    )
    phase_a_parser.add_argument(
        "--output-dir",
        default=None,
    )
    phase_a_parser.set_defaults(func=cmd_candidate_phase_a)

    candidate_report_parser = subparsers.add_parser(
        "candidate-report",
        help="Render candidate analysis artifacts as Markdown plus Mermaid visualizations",
    )
    candidate_report_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    candidate_report_parser.add_argument(
        "--input-dir",
        default=None,
    )
    candidate_report_parser.add_argument(
        "--output",
        default=None,
    )
    candidate_report_parser.add_argument(
        "--scope-path",
        default=None,
    )
    candidate_report_parser.add_argument(
        "--project-root",
        default=None,
    )
    candidate_report_parser.add_argument(
        "--cbm-binary",
        default=None,
    )
    demo_group = candidate_report_parser.add_mutually_exclusive_group()
    demo_group.add_argument(
        "--include-demo-artifacts",
        dest="include_demo_artifacts",
        action="store_true",
        help="Include example semantic searches and search-hit diagrams in the report",
    )
    demo_group.add_argument(
        "--no-demo-artifacts",
        dest="include_demo_artifacts",
        action="store_false",
        help="Suppress example semantic searches and search-hit diagrams in the report",
    )
    candidate_report_parser.set_defaults(include_demo_artifacts=None)
    candidate_report_parser.set_defaults(func=cmd_candidate_report)

    candidate_search_parser = subparsers.add_parser(
        "candidate-search",
        help="Run CBM search_graph with defaults from candidate_analysis config",
    )
    candidate_search_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    candidate_search_parser.add_argument("--project-root", default=None)
    candidate_search_parser.add_argument("--project-name", default=None)
    candidate_search_parser.add_argument("--cbm-binary", default=None)
    candidate_search_parser.add_argument(
        "--profile",
        default=None,
        help="Name of a configured semantic_query_profile to run",
    )
    candidate_search_parser.add_argument(
        "--semantic-query",
        default=None,
        help="Semantic terms as JSON array or comma-separated list; overrides profile/config",
    )
    candidate_search_parser.add_argument("--scope-path", default=None)
    candidate_search_parser.add_argument(
        "--scope-qn-prefix",
        default=None,
        help="Qualified-name prefix used to keep dependency searches inside the configured package scope",
    )
    candidate_search_parser.add_argument(
        "--file-pattern",
        default=None,
        help="CBM file pattern; defaults to '<scope-path>/*'",
    )
    candidate_search_parser.add_argument("--label", default=None)
    candidate_search_parser.add_argument("--limit", type=int, default=None)
    candidate_search_parser.add_argument(
        "--format",
        default="json",
        choices=["json", "tree"],
    )
    candidate_search_parser.add_argument(
        "--cbm-options",
        default=None,
        help="Raw CBM flags tail as '--flag value --flag2 value2'; added after wrapper defaults",
    )
    candidate_search_parser.set_defaults(func=cmd_candidate_search)

    quality_parser = subparsers.add_parser(
        "quality-report",
        help="Analyze module dependencies, cycles, complexity, duplicates, unused functions, and move candidates",
    )
    quality_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    quality_parser.add_argument("--project-root", default=None)
    quality_parser.add_argument("--scope-path", default=None)
    quality_parser.add_argument("--output-dir", default=None)
    quality_parser.set_defaults(func=cmd_quality_report)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
