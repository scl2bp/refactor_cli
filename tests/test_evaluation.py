import json
from pathlib import Path

from refactor_cli.analysis.evaluation import evaluate_candidate_artifacts


def test_evaluation_uses_report_semantic_scope_accounting(tmp_path: Path):
    semantic = {
        "result": {
            "payload": {
                "structuredContent": {
                    "semantic": {
                        "rows": [
                            ["local", "Function", "src/pkg/a.py", 1.0],
                            ["external.eval.hit", "Function", ".eval/pkg.py", 0.9],
                            ["excluded.eval.hit", "Function", "src/pkg/b.py", 0.8],
                        ]
                    }
                }
            }
        }
    }
    _write_required_artifacts(tmp_path, semantic)

    result = evaluate_candidate_artifacts(
        input_dir=tmp_path,
        output_path=tmp_path / "evaluation.json",
    )

    assert result["semantic"] == {
        "raw": 3,
        "local": 1,
        "non_local": 0,
        "discarded": 2,
    }
    assert result["checks"]["semantic_results_are_local"] is False
    assert result["quality"]["semantic_locality"] == {
        "affected": 2,
        "total": 3,
        "accepted": 1,
        "coverage_percent": 33.33,
        "loss_percent": 66.67,
        "grade": "CRITICAL",
    }


def test_quality_summary_distinguishes_small_and_large_degradation():
    from refactor_cli.analysis.quality import quality_summary

    assert quality_summary(total=1000, affected=1)["grade"] == "MINOR"
    assert quality_summary(total=100, affected=99)["grade"] == "CRITICAL"
    assert quality_summary(total=0, affected=0)["grade"] == "NOT_MEASURABLE"


def _write_required_artifacts(input_dir: Path, semantic: dict) -> None:
    baseline = {
        "scope_path": "src/pkg",
        "counts": {
            "configured_files": 1,
            "parsed_files": 1,
            "parse_errors": 0,
        },
        "modules": [{"module": "pkg", "file": "src/pkg/__init__.py"}],
        "internal_import_edges": [],
    }
    source_index = {
        "staged_files": ["src/pkg/__init__.py"],
        "index": {"payload": {"structuredContent": {}}},
    }
    dependency = {"result": {"payload": {"content": [{"text": "rows: 0"}]}}}
    summary = {
        "scope": {
            "scope_path": "src/pkg",
            "scope_qn_prefix": "pkg",
            "exclude_qn_substrings": [".eval."],
        }
    }
    architecture = {}
    for name, value in {
        "scope_baseline.json": baseline,
        "source_index.json": source_index,
        "dependency_graph.json": dependency,
        "semantic_retrieval.json": semantic,
        "architecture_report.json": architecture,
        "summary.json": summary,
    }.items():
        (input_dir / name).write_text(json.dumps(value), encoding="utf-8")