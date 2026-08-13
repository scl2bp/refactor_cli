from __future__ import annotations

from pathlib import Path
from typing import Any

from refactor_cli.candidate_tools import run_cbm_tool


def collect_semantic_retrieval(
    *,
    cbm_binary: Path,
    project_root: Path,
    project_name: str,
    semantic_terms: list[str],
    limit: int = 100,
    file_pattern: str | None = None,
) -> dict[str, Any]:
    flags: dict[str, Any] = {
        "project": project_name,
        "semantic_query": semantic_terms,
        "limit": limit,
        "format": "json",
    }
    if file_pattern:
        flags["file_pattern"] = file_pattern

    result = run_cbm_tool(
        cbm_binary,
        "search_graph",
        flags,
        cwd=project_root,
    )
    return {
        "provider": "codebase-memory-mcp",
        "project_name": project_name,
        "semantic_terms": semantic_terms,
        "limit": limit,
        "file_pattern": file_pattern,
        "result": result,
        "ok": result["ok"],
    }
