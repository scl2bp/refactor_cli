from pathlib import Path

from refactor_cli.candidate_report import (
    _fallback_dependency_rows,
    _mermaid_structural_hits,
    _search_hit_dependency_block,
    _search_hit_dependency_rows,
)


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
    assert any(
        "candidate_report" in source and "collect_dependency_graph" in target
        for source, _, target in rows
    )


def test_mermaid_structural_hits_differ_per_example():
    rows_ex1 = [("src/refactor_cli/candidate_report.py", "build_candidate_report", "Function")]
    rows_ex2 = [
        ("src/refactor_cli/__init__.py", "cmd_candidate_phase_a", "Function"),
        ("src/refactor_cli/source_index.py", "run_source_index", "Function"),
    ]
    rows_ex3 = [("src/refactor_cli/runtime_tools.py", "run_compile_check_on_file", "Function")]

    d1 = _mermaid_structural_hits(rows_ex1)
    d2 = _mermaid_structural_hits(rows_ex2)
    d3 = _mermaid_structural_hits(rows_ex3)

    assert "build_candidate_report" in d1
    assert "cmd_candidate_phase_a" in d2
    assert "run_compile_check_on_file" in d3
    # All three must differ
    assert d1 != d2
    assert d2 != d3
    assert d1 != d3


def test_mermaid_structural_hits_empty_shows_fallback():
    result = _mermaid_structural_hits([])
    assert "No matching symbols found" in result

    rows = [
        ("refactor_cli.candidate_report", "SEARCH_HIT", "build_candidate_report"),
        ("build_candidate_report", "SEARCH_HIT", "collect_dependency_graph"),
    ]

    block = _search_hit_dependency_block(rows, "src/refactor_cli")

    assert "Search-hit Dependency View" in block
    assert "flowchart LR" in block
    assert "build_candidate_report" in block
    assert "collect_dependency_graph" in block
