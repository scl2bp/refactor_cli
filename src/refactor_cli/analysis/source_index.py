import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from refactor_cli.analysis.candidate_tools import run_cbm_tool
from refactor_cli.discovery import (
    discover_python_files,
    load_config,
    resolve_project_root,
)


import subprocess


def _project_name_from_root(project_root: Path) -> str:
    return project_root.resolve().name


def _stage_configured_files(project_root: Path, files: list[Path]) -> Path:
    staging_root = Path(tempfile.mkdtemp(prefix="refactor-cli-cbm-"))
    for source in files:
        relative = source.relative_to(project_root)
        destination = staging_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    subprocess.run(["git", "init", "-q"], cwd=staging_root, check=True)
    subprocess.run(["git", "config", "user.email", "refactor-cli@example.invalid"], cwd=staging_root, check=True)
    subprocess.run(["git", "config", "user.name", "refactor-cli"], cwd=staging_root, check=True)
    subprocess.run(["git", "add", "."], cwd=staging_root, check=True)
    subprocess.run(["git", "commit", "-qm", "configured analysis corpus"], cwd=staging_root, check=True)
    return staging_root


def run_source_index(
    *,
    project_root: Path,
    cbm_binary: Path,
    project_name: str | None,
    config_path: Path | None = None,
    mode: str = "moderate",
) -> dict[str, Any]:
    resolved_root = project_root.resolve()
    resolved_name = project_name or _project_name_from_root(resolved_root)
    staged_repo_path = resolved_root
    staging_root: Path | None = None
    staged_files: list[str] = []
    config_summary: dict[str, Any] | None = None

    if config_path is not None and config_path.exists():
        config = load_config(config_path)
        config_root = resolve_project_root(config_path, config)
        files = discover_python_files(config_root, config)
        staged_files = [path.relative_to(config_root).as_posix() for path in files]
        config_summary = {
            "config_path": str(config_path.resolve()),
            "project_root": str(config_root),
            "file_count": len(staged_files),
        }
        staging_root = _stage_configured_files(config_root, files)
        staged_repo_path = staging_root

    try:
        index_result = run_cbm_tool(
            cbm_binary,
            "index_repository",
            {
                "repo_path": str(staged_repo_path.resolve()),
                "mode": mode,
                "name": resolved_name,
            },
            cwd=resolved_root,
        )
        if not index_result["ok"] and mode != "fast":
            index_result = run_cbm_tool(
                cbm_binary,
                "index_repository",
                {
                    "repo_path": str(staged_repo_path.resolve()),
                    "mode": "fast",
                    "name": resolved_name,
                },
                cwd=resolved_root,
            )
    finally:
        if staging_root is not None:
            shutil.rmtree(staging_root, ignore_errors=True)

    projects_result = run_cbm_tool(cbm_binary, "list_projects", {}, cwd=project_root)

    return {
        "provider": "codebase-memory-mcp",
        "project_root": str(project_root.resolve()),
        "project_name": resolved_name,
        "mode": mode,
        "config_summary": config_summary,
        "staged_files": staged_files,
        "index": index_result,
        "projects": projects_result,
        "ok": index_result["ok"] and projects_result["ok"],
    }


def run_coderag_validate_only(
    *,
    coderag_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    required = ["NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        return {
            "provider": "CodeRAG",
            "ok": None,
            "skipped": True,
            "reason": "Missing required Neo4j environment variables",
            "missing_env": missing,
        }

    cmd = [
        "npm",
        "run",
        "-s",
        "scan:built",
        "--",
        "validate",
        str(project_root.resolve()),
    ]
    result = subprocess.run(
        cmd,
        cwd=str(coderag_root),
        capture_output=True,
        text=True,
    )
    return {
        "provider": "CodeRAG",
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "command": cmd,
        "cwd": str(coderag_root.resolve()),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
