from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from refactor_cli.candidate_tools import run_cbm_tool


def _project_name_from_root(project_root: Path) -> str:
    return project_root.resolve().name


def run_source_index(
    *,
    project_root: Path,
    cbm_binary: Path,
    project_name: str | None,
    mode: str = "moderate",
) -> dict[str, Any]:
    resolved_name = project_name or _project_name_from_root(project_root)
    index_result = run_cbm_tool(
        cbm_binary,
        "index_repository",
        {
            "repo_path": str(project_root.resolve()),
            "mode": mode,
            "name": resolved_name,
        },
        cwd=project_root,
    )

    projects_result = run_cbm_tool(cbm_binary, "list_projects", {}, cwd=project_root)

    return {
        "provider": "codebase-memory-mcp",
        "project_root": str(project_root.resolve()),
        "project_name": resolved_name,
        "mode": mode,
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
