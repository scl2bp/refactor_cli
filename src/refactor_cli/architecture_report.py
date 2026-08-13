from __future__ import annotations

from pathlib import Path
from typing import Any

from refactor_cli.candidate_tools import run_cbm_tool


def collect_architecture_report(
    *,
    cbm_binary: Path,
    project_root: Path,
    project_name: str,
    aspects: list[str] | None = None,
    scope_path: str | None = None,
) -> dict[str, Any]:
    report_aspects = aspects or ["overview"]
    if len(report_aspects) == 1:
        aspects_flag: str | list[str] = report_aspects[0]
    else:
        aspects_flag = report_aspects
    flags: dict[str, Any] = {
        "project": project_name,
        "aspects": aspects_flag,
    }
    if scope_path:
        flags["path"] = scope_path

    result = run_cbm_tool(
        cbm_binary,
        "get_architecture",
        flags,
        cwd=project_root,
    )
    return {
        "provider": "codebase-memory-mcp",
        "project_name": project_name,
        "aspects": report_aspects,
        "scope_path": scope_path,
        "result": result,
        "ok": result["ok"],
    }
