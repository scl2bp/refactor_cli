from pathlib import Path
from argparse import Namespace

import refactor_cli.cli.commands as commands
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


def test_quality_gate_coverage_follows_configured_scope(tmp_path: Path, monkeypatch):
    config_path = tmp_path / ".refactor" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(
        '{"python_files": {"include": ["backend/**/*.py"]}}',
        encoding="utf-8",
    )
    captured: list[str] = []
    monkeypatch.setattr(commands, "run_quality_gate", lambda arguments: captured.extend(arguments) or 0)

    result = commands.cmd_quality_gate(
        Namespace(
            config=str(config_path),
            project_root=str(tmp_path),
            scope_path=None,
            paths=None,
            output_dir=None,
            refresh_baseline=False,
            no_coverage=False,
            no_cache=False,
            fail_on_gate=False,
        )
    )

    coverage_command = captured[captured.index("--coverage-command") + 1]
    assert result == 0
    assert "--cov=\"backend\"" in coverage_command
    assert "src/refactor_cli" not in coverage_command