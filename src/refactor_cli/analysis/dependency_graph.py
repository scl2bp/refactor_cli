from pathlib import Path
from typing import Any

from refactor_cli.analysis.candidate_tools import run_cbm_tool


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
    scope_qn_prefix: str | None = None,
    exclude_qn_substrings: list[str] | None = None,
) -> dict[str, Any]:
    query = EDGE_QUERY
    filters: list[str] = []
    if scope_qn_prefix:
        filters.append(f"coalesce(s.qn, s.name) STARTS WITH '{scope_qn_prefix}'")
    for token in exclude_qn_substrings or []:
        escaped = token.replace("'", "\\'")
        filters.append(
            f"NOT coalesce(s.qn, s.name) CONTAINS '{escaped}' "
            f"AND NOT coalesce(t.qn, t.name) CONTAINS '{escaped}'"
        )
    if filters:
        query = (
            "MATCH (s)-[r:CALLS|IMPORTS|INHERITS]->(t) "
            f"WHERE {' AND '.join(filters)} "
            "RETURN coalesce(s.qn, s.name) AS source, "
            "type(r) AS relation, "
            "coalesce(t.qn, t.name) AS target"
        )

    result = run_cbm_tool(
        cbm_binary,
        "query_graph",
        {
            "project": project_name,
            "query": query,
            "max_rows": max_rows,
        },
        cwd=project_root,
    )
    return {
        "provider": "codebase-memory-mcp",
        "project_name": project_name,
        "query": query,
        "max_rows": max_rows,
        "scope_qn_prefix": scope_qn_prefix,
        "exclude_qn_substrings": exclude_qn_substrings or [],
        "result": result,
        "ok": result["ok"],
    }
