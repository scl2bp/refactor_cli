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


from refactor_cli.analysis.candidate_tools import resolve_cbm_binary


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


from refactor_cli.transforms import (
    apply_unified_diff_to_text,
    build_after_tree_from_edit,
    run_tree_transition,
)


from refactor_cli.tree_codec import (
    load_tree_yaml,
    write_tree_yaml,
)


from refactor_cli.config.settings import (
    DEFAULT_APPLIED_PATCHES_DIR,
    DEFAULT_CANDIDATE_OUTPUT_DIR,
    DEFAULT_CANDIDATE_REPORT,
    DEFAULT_CONFIG,
    DEFAULT_TREE,
    DEFAULT_TREE_EDIT,
    DEFAULT_TREE_PATCH,
    _candidate_analysis_config,
    _config_or_default,
    _find_default_config_path,
    _load_optional_config,
    _load_summary_if_present,
    _resolve_optional_project_root,
    _resolve_path_setting,
    _semantic_query_profiles_setting,
    _semantic_terms_setting,
    _exclude_substrings_setting,
)


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


def main() -> int:

    from refactor_cli.cli.parser import build_parser

    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
