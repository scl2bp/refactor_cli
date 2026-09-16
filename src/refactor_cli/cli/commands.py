import argparse
from refactor_cli import _resolve_candidate_phase_a_settings
from refactor_cli.file_io import write_json
from refactor_cli import _resolve_candidate_report_settings
from refactor_cli import _resolve_candidate_search_settings
from typing import Any
import json
from pathlib import Path
from refactor_cli.config.settings import (
    _candidate_analysis_config,
    _config_or_default,
    _load_optional_config,
    _resolve_optional_project_root,
)
from refactor_cli.discovery import discover_python_files
from refactor_cli.analysis.architecture_report import collect_architecture_report
from refactor_cli.analysis.candidate_tools import run_cbm_tool
from refactor_cli.analysis.dependency_graph import collect_dependency_graph
from refactor_cli.analysis.internal_dependencies_report import write_quality_report
from refactor_cli.analysis.quality_gate import run_quality_gate
from refactor_cli.analysis.semantic_retrieval import collect_semantic_retrieval
from refactor_cli.analysis.source_index import run_coderag_validate_only, run_source_index
from refactor_cli.analysis.scope_baseline import collect_scope_baseline
from refactor_cli.analysis.evaluation import evaluate_candidate_artifacts
from refactor_cli.candidate_report import build_candidate_report
from refactor_cli.runtime_tools import ensure_runtime_dependencies


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
    config = _load_optional_config(settings["config_path"])
    configured_files = discover_python_files(project_root, config)
    scope_baseline = collect_scope_baseline(
        project_root=project_root,
        scope_path=(project_root / scope_path),
        files=configured_files,
    )
    write_json(output_dir / "scope_baseline.json", scope_baseline)

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
            "scope_baseline": True,
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


def cmd_candidate_evaluate(args: argparse.Namespace) -> int:
    settings = _resolve_candidate_report_settings(args)
    output_path = Path(args.output or settings["input_dir"] / "evaluation.json")
    result = evaluate_candidate_artifacts(
        input_dir=settings["input_dir"],
        output_path=output_path,
    )
    print(f"CANDIDATE EVALUATION {result['status']}")
    print(f"  input: {settings['input_dir']}")
    print(f"  output: {output_path}")
    print(f"  automation-ready: {'YES' if result['ready_for_automation'] else 'NO'}")
    for name, details in result.get("quality", {}).items():
        coverage = details.get("coverage_percent")
        loss = details.get("loss_percent")
        print(
            f"  {name}: {details['affected']}/{details['total']} affected, "
            f"coverage={coverage if coverage is not None else 'n/a'}%, "
            f"loss={loss if loss is not None else 'n/a'}%, grade={details['grade']}"
        )
    return 0 if result["status"] != "FAIL" else 1


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


def cmd_internal_dependencies_report(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = _load_optional_config(config_path)
    analysis = _candidate_analysis_config(config)
    project_root = _resolve_optional_project_root(
        args.project_root, config_path, config
    )
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
        json_path=output_dir / "internal_module_dependencies.json",
        markdown_path=output_dir / "internal_module_dependencies.md",
    )
    print("QUALITY REPORT WRITTEN")
    print(f"  scope: {scope_path}")
    print(f"  modules: {len(payload['modules'])}")
    print(f"  move candidates: {len(payload['move_candidates'])}")
    print(f"  duplicate groups: {len(payload['duplicate_groups'])}")
    print(f"  unused functions: {len(payload['unused_functions'])}")
    return 0


def cmd_quality_gate(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = _load_optional_config(config_path)
    analysis = _candidate_analysis_config(config)
    project_root = _resolve_optional_project_root(
        args.project_root, config_path, config
    )
    output_dir = Path(args.output_dir or ".refactor/analysis/quality")
    if not output_dir.is_absolute():
        output_dir = (project_root / output_dir).resolve()
    scope_path = args.scope_path or analysis.get("scope_path") or "src"
    paths = args.paths or [scope_path]
    arguments = [
        "--repo-root", str(project_root),
        "--paths", *paths,
        "--baseline-path", str(output_dir / "complexity_baseline.json"),
        "--stats-path", str(output_dir / "complexity_current.json"),
        "--report-path", str(output_dir / "complexity_report.md"),
    ]
    if args.refresh_baseline:
        arguments.append("--refresh-baseline")
    if args.no_coverage:
        arguments.append("--no-coverage")
    if args.fail_on_gate:
        arguments.append("--strict")
    return run_quality_gate(arguments)


cmd_quality_report = cmd_quality_gate
