from pathlib import Path

from refactor_cli.analysis.quality_gate import run_quality_gate
from refactor_cli.config.settings import _configured_scope_paths


def test_configured_scope_paths_infer_directories_from_include_patterns():
    config = {
        "python_files": {
            "include": ["backend/**/*.py", "tools/*.py", "**/*.py"]
        }
    }

    assert _configured_scope_paths(config) == ["backend", "tools", "."]


def test_quality_gate_creates_and_enforces_baseline(tmp_path: Path):
    source_dir = tmp_path / "src" / "demo"
    source_dir.mkdir(parents=True)
    (source_dir / "module.py").write_text(
        "def calculate(value: int) -> int:\n    return value + 1\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "quality" / "complexity_baseline.json"
    current = tmp_path / "quality" / "complexity_current.json"
    report = tmp_path / "quality" / "complexity_report.md"

    arguments = [
        "--repo-root", str(tmp_path),
        "--paths", "src",
        "--baseline-path", str(baseline),
        "--stats-path", str(current),
        "--report-path", str(report),
        "--no-coverage",
    ]

    assert run_quality_gate([*arguments, "--refresh-baseline"]) == 0
    assert baseline.exists()
    assert report.exists()
    assert run_quality_gate([*arguments, "--strict"]) == 0