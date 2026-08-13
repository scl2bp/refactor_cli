from pathlib import Path

from refactor_cli.candidate_report import _fallback_dependency_rows, _search_hit_dependency_rows


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "src" / "refactor_cli"


def test_fallback_dependency_rows_are_non_empty_for_package():
    rows = _fallback_dependency_rows(PACKAGE_DIR)

    assert rows
    assert any(
        source.endswith("__init__") and target.endswith("candidate_report")
        for source, _, target in rows
    )


def test_search_hit_dependency_rows_are_generated_from_local_hits():
    semantic_doc = {
        "result": {
            "payload": {
                "structuredContent": {
                    "groups": [
                        {
                            "file": "src/refactor_cli/candidate_report.py",
                            "rows": [["build_candidate_report", "Function", 10, 2, 5]],
                        },
                        {
                            "file": "src/refactor_cli/dependency_graph.py",
                            "rows": [["collect_dependency_graph", "Function", 8, 1, 3]],
                        },
                    ]
                }
            }
        }
    }

    rows = _search_hit_dependency_rows(semantic_doc, "src/refactor_cli")

    assert rows
    assert any("candidate_report" in source and "collect_dependency_graph" in target for source, _, target in rows)
