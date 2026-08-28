import argparse
import json
from pathlib import Path

from refactor_cli.__init__ import (
    _resolve_candidate_phase_a_settings,
    _resolve_candidate_report_settings,
)
from refactor_cli.candidate_report import (
    _fallback_dependency_rows,
    _optional_demo_artifacts_section,
    _parse_relation_rows,
    _mermaid_structural_hits,
    _search_hit_dependency_block,
    _search_hit_dependency_rows,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "src" / "refactor_cli"


def test_fallback_dependency_rows_are_non_empty_for_package():
    rows = _fallback_dependency_rows(PACKAGE_DIR, package_prefix="refactor_cli")

    assert rows
    assert any(
        source.endswith("__init__") and target.endswith("candidate_report")
        for source, _, target in rows
    )


def test_parse_relation_rows_handles_generic_cbm_output():
    rows = _parse_relation_rows(
        "rows: 2  (cols: source relation target)\n"
        "pkg.alpha IMPORTS pkg.beta\n"
        "pkg.alpha CALLS pkg.beta.func\n"
        'hint: "Query returned no results."\n'
    )

    assert rows == [
        ("pkg.alpha", "IMPORTS", "pkg.beta"),
        ("pkg.alpha", "CALLS", "pkg.beta.func"),
    ]


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


def test_demo_artifacts_section_is_opt_in():
    hidden = _optional_demo_artifacts_section(
        include_demo_artifacts=False,
        scope_path="src/refactor_cli",
        representative_report="demo body",
        search_hit_rows=[("a", "SEARCH_HIT", "b")],
    )
    shown = _optional_demo_artifacts_section(
        include_demo_artifacts=True,
        scope_path="src/refactor_cli",
        representative_report="demo body",
        search_hit_rows=[("a", "SEARCH_HIT", "b")],
    )

    assert "Representative semantic searches" not in hidden
    assert "--include-demo-artifacts" in hidden
    assert "Representative semantic searches" in shown
    assert "Search-hit Dependency View" in shown


def test_candidate_phase_a_uses_project_config_defaults(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    refactor_dir = project_root / ".refactor"
    refactor_dir.mkdir()
    config_path = refactor_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "project_root": "..",
                "python_files": {"include": ["src/**/*.py"], "exclude": []},
                "candidate_analysis": {
                    "project_name": "demo-project",
                    "index_mode": "moderate",
                    "max_rows": 123,
                    "semantic_terms": ["module", "dependency"],
                    "semantic_limit": 17,
                    "scope_path": "src/demo_pkg",
                    "scope_qn_prefix": "demo_pkg",
                    "exclude_qn_substrings": [".eval.", "tests"],
                    "output_dir": ".refactor/analysis/custom",
                    "report_output": ".refactor/analysis/custom/report.md",
                    "include_demo_artifacts": True,
                    "semantic_query_profiles": [
                        {
                            "name": "Input processing",
                            "query": "config parse",
                            "why": "find loaders",
                            "scope_path": "src/demo_pkg",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    args = argparse.Namespace(
        config=str(config_path),
        project_root=None,
        project_name=None,
        cbm_binary="/bin/echo",
        index_mode=None,
        max_rows=None,
        semantic_terms=None,
        semantic_limit=None,
        scope_path=None,
        scope_qn_prefix=None,
        exclude_qn_substring=None,
        include_coderag_validate=None,
        coderag_path=None,
        output_dir=None,
    )

    settings = _resolve_candidate_phase_a_settings(args)

    assert settings["project_root"] == project_root.resolve()
    assert settings["project_name"] == "demo-project"
    assert settings["max_rows"] == 123
    assert settings["semantic_terms"] == ["module", "dependency"]
    assert settings["scope_path"] == "src/demo_pkg"
    assert settings["scope_qn_prefix"] == "demo_pkg"
    assert settings["exclude_qn_substrings"] == [".eval.", "tests"]
    assert settings["output_dir"] == (project_root / ".refactor/analysis/custom").resolve()
    assert settings["semantic_query_profiles"][0]["name"] == "Input processing"


def test_candidate_report_uses_project_config_defaults_and_summary_scope(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    refactor_dir = project_root / ".refactor"
    analysis_dir = refactor_dir / "analysis" / "custom"
    analysis_dir.mkdir(parents=True)
    config_path = refactor_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "project_root": "..",
                "python_files": {"include": ["src/**/*.py"], "exclude": []},
                "candidate_analysis": {
                    "cbm_binary": "/bin/echo",
                    "output_dir": ".refactor/analysis/custom",
                    "report_output": ".refactor/analysis/custom/architecture.md",
                    "include_demo_artifacts": False,
                    "semantic_query_profiles": [
                        {
                            "name": "Report generation",
                            "query": "report export",
                            "why": "find outputs",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (analysis_dir / "summary.json").write_text(
        json.dumps(
            {
                "project_root": str(project_root.resolve()),
                "project_name": "demo-project",
                "cbm_binary": "/bin/echo",
                "scope": {"scope_path": "src/demo_pkg", "scope_qn_prefix": "demo_pkg"},
                "modules": {},
            }
        ),
        encoding="utf-8",
    )

    args = argparse.Namespace(
        config=str(config_path),
        input_dir=None,
        output=None,
        scope_path=None,
        project_root=None,
        cbm_binary=None,
        include_demo_artifacts=None,
    )

    settings = _resolve_candidate_report_settings(args)

    assert settings["project_root"] == project_root.resolve()
    assert settings["input_dir"] == analysis_dir.resolve()
    assert settings["output_path"] == (analysis_dir / "architecture.md").resolve()
    assert settings["scope_path"] == "src/demo_pkg"
    assert settings["cbm_binary"] == "/bin/echo"
    assert settings["include_demo_artifacts"] is False
    assert settings["semantic_query_profiles"][0]["name"] == "Report generation"
