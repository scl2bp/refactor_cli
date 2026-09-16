from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from refactor_cli.candidate_report import (
    _compare_ast_cbm_imports,
    _dependency_rows_from_text,
    _extract_text_content,
    _semantic_noise_summary,
    _scope_qn_prefix,
)
from refactor_cli.analysis.quality import quality_summary
from refactor_cli.file_io import load_json


REQUIRED_ARTIFACTS = (
    "scope_baseline.json",
    "source_index.json",
    "dependency_graph.json",
    "semantic_retrieval.json",
    "architecture_report.json",
    "summary.json",
)


def evaluate_candidate_artifacts(
    *, input_dir: Path, output_path: Path
) -> dict[str, Any]:
    input_dir = input_dir.resolve()
    missing = [name for name in REQUIRED_ARTIFACTS if not (input_dir / name).exists()]
    if missing:
        result = {
            "status": "FAIL",
            "ready_for_automation": False,
            "input_dir": str(input_dir),
            "missing_artifacts": missing,
            "checks": {},
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result

    summary = load_json(input_dir / "summary.json")
    baseline = load_json(input_dir / "scope_baseline.json")
    source_index = load_json(input_dir / "source_index.json")
    dependency = load_json(input_dir / "dependency_graph.json")
    semantic = load_json(input_dir / "semantic_retrieval.json")
    scope = summary.get("scope", {})
    scope_path = str(scope.get("scope_path", baseline.get("scope_path", "")))
    scope_prefix = _scope_qn_prefix(summary, scope_path)
    index = source_index.get("index", {}).get("payload", {}).get("structuredContent", {})
    cbm_rows = _dependency_rows_from_text(
        _extract_text_content(dependency.get("result", {}).get("payload", {}))
    )
    comparison = _compare_ast_cbm_imports(baseline, cbm_rows, scope_prefix)
    baseline_counts = baseline.get("counts", {})
    staged_count = len(source_index.get("staged_files", []))
    semantic_counts = _semantic_noise_summary(
        semantic,
        scope_path,
        exclude_substrings=scope.get("exclude_qn_substrings", []),
    )
    quality = {
        "configured_files": quality_summary(
            total=baseline_counts.get("configured_files", 0),
            affected=(
                baseline_counts.get("parse_errors", 0)
                + max(0, baseline_counts.get("configured_files", 0) - staged_count)
            ),
        ),
        "cbm_import_agreement": quality_summary(
            total=max(comparison["ast_edges"], comparison["cbm_edges"]),
            affected=len(comparison["missing_from_cbm"])
            + len(comparison["extra_in_cbm"]),
        ),
        "semantic_locality": quality_summary(
            total=semantic_counts["raw"],
            affected=semantic_counts["non_local"] + semantic_counts["discarded"],
        ),
    }
    checks = {
        "required_artifacts": not missing,
        "configured_files_match_staged": staged_count == baseline_counts.get("configured_files"),
        "configured_files_accounted_for": (
            baseline_counts.get("configured_files")
            == baseline_counts.get("parsed_files", 0) + baseline_counts.get("parse_errors", 0)
        ),
        "cbm_has_no_partial_or_unindexed_files": (
            index.get("parse_partial_count", 0) == 0
            and index.get("not_indexed_files_count", 0) == 0
        ),
        "ast_cbm_imports_agree": not comparison["missing_from_cbm"] and not comparison["extra_in_cbm"],
        "semantic_results_are_local": (
            semantic_counts["non_local"] == 0
            and semantic_counts["discarded"] == 0
        ),
    }
    status = "OK" if all(checks.values()) else "DEGRADED"
    result = {
        "status": status,
        "ready_for_automation": status == "OK",
        "input_dir": str(input_dir),
        "scope": {
            "path": scope_path,
            "qn_prefix": scope_prefix,
            "configured_files": baseline_counts.get("configured_files", 0),
            "parsed_files": baseline_counts.get("parsed_files", 0),
            "parse_errors": baseline_counts.get("parse_errors", 0),
            "staged_files": staged_count,
        },
        "index": {
            "partial_parses": index.get("parse_partial_count", 0),
            "unindexed_files": index.get("not_indexed_files_count", 0),
        },
        "semantic": semantic_counts,
        "ast_cbm_imports": comparison,
        "quality": quality,
        "checks": checks,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result