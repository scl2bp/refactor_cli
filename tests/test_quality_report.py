from pathlib import Path

from refactor_cli.analysis.quality_report import collect_quality_report, render_quality_report


def test_quality_report_recovers_internal_module_dependencies(tmp_path: Path):
    package = tmp_path / "demo_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("from demo_pkg.api import run\n", encoding="utf-8")
    (package / "api.py").write_text(
        "from demo_pkg.core import calculate\nfrom demo_pkg.helper import label\n\ndef run():\n    return label(calculate())\n",
        encoding="utf-8",
    )
    (package / "core.py").write_text("def calculate():\n    return 1\n", encoding="utf-8")
    (package / "helper.py").write_text("def label(value):\n    return value\n", encoding="utf-8")

    report = collect_quality_report(project_root=tmp_path, scope_path=package)

    api = next(row for row in report["modules"] if row["module"] == "demo_pkg.api")
    assert api["imports"] == ["demo_pkg.core", "demo_pkg.helper"]
    assert report["cycles"] == []
    assert any(row["module"] == "demo_pkg.api" for row in report["move_candidates"])


def test_quality_report_renders_move_and_duplicate_sections():
    markdown = render_quality_report(
        {
            "package": "demo_pkg",
            "scope": "src/demo_pkg",
            "move_candidates": [{"module": "demo_pkg.api", "reason": "high fan-out", "fan_out": 2}],
            "modules": [],
            "cycles": [],
            "dependency_paths": [],
            "mermaid": "flowchart LR",
            "complexity": [],
            "duplicate_groups": [],
            "unused_functions": [],
        }
    )

    assert "## Move Candidates" in markdown
    assert "demo_pkg.api" in markdown
    assert "## Duplicates" in markdown