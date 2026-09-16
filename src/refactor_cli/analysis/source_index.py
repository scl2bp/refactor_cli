import os
from pathlib import Path
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
        # Always index the real project root so CBM can find the .git dir and
        # parse Python symbols. A staging-dir copy has no .git, so CBM would
        # only produce Project/Branch metadata nodes with no code content.
        staged_repo_path = config_root

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
