from pathlib import Path

from refactor_cli.analysis.scope_baseline import collect_scope_baseline


def test_scope_baseline_separates_internal_and_external_imports(tmp_path: Path):
    package = tmp_path / "src" / "demo_pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("from demo_pkg.api import run\n", encoding="utf-8")
    (package / "api.py").write_text(
        "from demo_pkg.core import calculate\nimport json\n\ndef run():\n    return calculate()\n",
        encoding="utf-8",
    )
    (package / "core.py").write_text("def calculate():\n    return 1\n", encoding="utf-8")

    result = collect_scope_baseline(
        project_root=tmp_path,
        scope_path=package,
        files=list(package.glob("*.py")),
    )

    assert result["counts"]["configured_files"] == 3
    assert result["counts"]["parsed_files"] == 3
    assert {row["target"] for row in result["internal_import_edges"]} == {
        "demo_pkg.api",
        "demo_pkg.core",
    }
    assert {row["import"] for row in result["external_imports"]} == {"json"}


def test_scope_baseline_reports_parse_errors_without_dropping_scope_files(tmp_path: Path):
    package = tmp_path / "src" / "demo_pkg"
    package.mkdir(parents=True)
    valid = package / "api.py"
    invalid = package / "broken.py"
    valid.write_text("import json\n", encoding="utf-8")
    invalid.write_text("def broken(:\n", encoding="utf-8")

    result = collect_scope_baseline(
        project_root=tmp_path,
        scope_path=package,
        files=[valid, invalid],
    )

    assert result["counts"] == {
        "configured_files": 2,
        "parsed_files": 1,
        "parse_errors": 1,
        "internal_import_edges": 0,
        "external_imports": 1,
    }
    assert result["parse_errors"][0]["file"] == "src/demo_pkg/broken.py"


def test_scope_baseline_resolves_top_level_imports_below_source_root(tmp_path: Path):
    backend = tmp_path / "backend"
    (backend / "api").mkdir(parents=True)
    (backend / "domain").mkdir()
    app = backend / "api" / "app.py"
    config = backend / "domain" / "config.py"
    app.write_text("from domain.config import load_config\n", encoding="utf-8")
    config.write_text("def load_config():\n    return None\n", encoding="utf-8")

    result = collect_scope_baseline(
        project_root=tmp_path,
        scope_path=tmp_path,
        files=[app, config],
    )

    assert result["counts"]["internal_import_edges"] == 1
    assert result["internal_import_edges"][0]["target"].endswith("backend.domain.config")