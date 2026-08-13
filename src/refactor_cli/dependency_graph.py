from __future__ import annotations

from pathlib import Path
from typing import Any

from refactor_cli.candidate_tools import run_cbm_tool


EDGE_QUERY = (
    "MATCH (s)-[r:CALLS|IMPORTS|INHERITS]->(t) "
    "RETURN coalesce(s.qn, s.name) AS source, "
    "type(r) AS relation, "
    "coalesce(t.qn, t.name) AS target"
)


def collect_dependency_graph(
    *,
    cbm_binary: Path,
    project_root: Path,
    project_name: str,
    max_rows: int = 5000,
) -> dict[str, Any]:
    result = run_cbm_tool(
        cbm_binary,
        "query_graph",
        {
            "project": project_name,
            "query": EDGE_QUERY,
            "max_rows": max_rows,
        },
        cwd=project_root,
    )
    return {
        "provider": "codebase-memory-mcp",
        "project_name": project_name,
        "query": EDGE_QUERY,
        "max_rows": max_rows,
        "result": result,
        "ok": result["ok"],
    }
