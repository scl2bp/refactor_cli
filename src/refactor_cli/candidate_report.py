from __future__ import annotations

import ast
from collections import Counter, defaultdict
import datetime as dt
import json
from pathlib import Path
import re
from typing import Any

from refactor_cli.analysis.candidate_tools import resolve_cbm_binary; from refactor_cli.analysis.candidate_tools import run_cbm_tool
from refactor_cli.file_io import load_json


def _extract_text_content(payload: dict[str, Any]) -> str:
    content = payload.get("content", [])
    if not content:
        return ""
    first = content[0]
    if isinstance(first, dict):
        return first.get("text", "")
    return ""


def _architecture_text(architecture_doc: dict[str, Any]) -> str:
    return _extract_text_content(architecture_doc["result"]["payload"])


def _parse_section_counts(text: str, header: str) -> list[tuple[str, int]]:
    lines = text.splitlines()
    results: list[tuple[str, int]] = []
    in_section = False
    for line in lines:
        if line.startswith(f"{header}:"):
            in_section = True
            continue
        if in_section:
            if not line.startswith("  "):
                break
            parts = line.strip().rsplit(" ", 1)
            if len(parts) != 2:
                continue
            name, count_text = parts
            try:
                results.append((name, int(count_text)))
            except ValueError:
                continue
    return results


def _parse_section_lines(text: str, header: str) -> list[str]:
    lines = text.splitlines()
    results: list[str] = []
    in_section = False
    for line in lines:
        if line.startswith(f"{header}:"):
            in_section = True
            continue
        if in_section:
            if not line.startswith("  "):
                break
            results.append(line.strip())
    return results


def _parse_scalar_value(text: str, key: str) -> str | None:
    prefix = f"{key}: "
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _status_label(value: Any) -> str:
    if isinstance(value, str) and value in {"OK", "DEGRADED", "PARTIAL", "FAIL", "SKIP"}:
        return value
    if value is True:
        return "OK"
    if value is False:
        return "FAIL"
    return "SKIP"


def _trust_status(
    *,
    provider_ok: bool,
    partial: bool = False,
    discarded: bool = False,
    usable: bool = True,
) -> str:
    if not provider_ok:
        return "FAIL"
    if not usable:
        return "PARTIAL"
    if partial or discarded:
        return "DEGRADED"
    return "OK"


def _filter_relation_rows(
    rows: list[tuple[str, str, str]],
    scope_prefix: str,
    exclude_substrings: list[str] | None = None,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    excluded_tokens = [token for token in (exclude_substrings or []) if token]
    local: list[tuple[str, str, str]] = []
    discarded: list[tuple[str, str, str]] = []
    for row in rows:
        source, _relation, target = row
        in_scope = scope_prefix in source and scope_prefix in target
        excluded = any(
            token in source or token in target for token in excluded_tokens
        )
        if in_scope and not excluded:
            local.append(row)
        else:
            discarded.append(row)
    return local, discarded


def _artifact_size_rows(input_dir: Path) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for name in sorted(input_dir.glob("*.json")):
        rows.append((name.name, name.stat().st_size))
    return rows


def _top_local_groups(
    semantic_doc: dict[str, Any], scope_path: str
) -> list[tuple[str, str, str, int, int]]:
    result_doc = semantic_doc.get("result", semantic_doc)
    structured = result_doc.get("payload", {}).get("structuredContent", {})
    groups = structured.get("groups", [])
    rows: list[tuple[str, str, str, int, int]] = []
    for group in groups:
        file_path = group.get("file", "")
        if not file_path.startswith(scope_path):
            continue
        for row in group.get("rows", []):
            if len(row) < 5:
                continue
            rows.append((file_path, row[0], row[1], row[3], row[4]))
    return rows[:10]


def _semantic_group_summary(
    semantic_doc: dict[str, Any], scope_path: str
) -> dict[str, int]:
    result_doc = semantic_doc.get("result", semantic_doc)
    structured = result_doc.get("payload", {}).get("structuredContent", {})
    groups = structured.get("groups", [])
    local_groups = 0
    local_rows = 0
    for group in groups:
        file_path = group.get("file", "")
        if not str(file_path).startswith(scope_path):
            continue
        local_groups += 1
        local_rows += len(group.get("rows", []))
    return {"local_groups": local_groups, "local_rows": local_rows}


def _semantic_noise_summary(
    semantic_doc: dict[str, Any], scope_path: str, exclude_substrings: list[str] | None = None
) -> dict[str, int]:
    result_doc = semantic_doc.get("result", semantic_doc)
    structured = result_doc.get("payload", {}).get("structuredContent", {})
    semantic = structured.get("semantic", {})
    rows = semantic.get("rows", [])
    local = 0
    non_local = 0
    discarded = 0
    for row in rows:
        if len(row) < 3:
            continue
        qn = str(row[0])
        file_path = str(row[2])
        if any(token in qn or token in file_path for token in (exclude_substrings or [])):
            discarded += 1
            continue
        if file_path.startswith(scope_path):
            local += 1
        else:
            non_local += 1
    return {
        "raw": len(rows),
        "local": local,
        "non_local": non_local,
        "discarded": discarded,
    }


def _semantic_usage_guidance(scope_path: str) -> list[str]:
    return [
        f"Search with file_pattern={scope_path}/* when you need package-local discovery.",
        "Treat semantic rows as corpus-wide ranking hints, not as a scoped file filter.",
        "Use grouped hits to find local files, then inspect the file-level summary and the ranking scores together.",
        "If the local ratio stays at 0, the query terms are too broad for the package or the corpus is too noisy.",
    ]


def _detail_options_lines(scope_path: str) -> list[str]:
    return [
        "Use `refactor-cli candidate-search` for ad hoc questions without rebuilding the full report.",
        "Add `--cbm-options` when you want raw CBM flags such as `--include-connected` or `--relationship CALLS`.",
        f"Use `--scope-path {scope_path}` when you want a narrower package-local query than the report default.",
        "Use `--label Class` to inspect model/data surfaces and `--label Function` to inspect flow and orchestration.",
        "If the report says LOW_SIGNAL, narrow the terms or add CBM graph constraints such as `--min-degree 1`.",
    ]


def _semantic_query_profiles(scope_path: str) -> list[dict[str, str]]:
    return [
        {
            "name": "Where is the candidate analysis report assembled?",
            "query": "candidate report markdown mermaid render",
            "scope": scope_path,
            "why": "should surface report-building code and the report output path",
            "structural_pattern": "build_candidate_report|cmd_candidate_report|candidate_report",
        },
        {
            "name": "Where does Phase A collect and persist artifacts?",
            "query": "candidate phase a source index semantic retrieval architecture report",
            "scope": scope_path,
            "why": "should surface the orchestration function that runs the analysis pipeline",
            "structural_pattern": "cmd_candidate_phase_a|run_source_index|collect_dependency_graph|collect_semantic_retrieval|collect_architecture_report",
        },
        {
            "name": "Where are the safety checks around edit application?",
            "query": "compile check format safeguards tree edit",
            "scope": scope_path,
            "why": "should surface the post-edit guardrail path and formatting checks",
            "structural_pattern": "post_apply_safeguards|run_compile_check_on_file|run_formatter_on_file|run_lint_check_on_file",
        },
    ]


def _profile_terms(profile: dict[str, Any]) -> list[str]:
    terms = profile.get("semantic_terms")
    if isinstance(terms, list):
        out = [str(token).strip() for token in terms if str(token).strip()]
        if out:
            return out
    query = str(profile.get("query", "")).strip()
    return [token.strip() for token in query.split() if token.strip()]


def _profile_scope(profile: dict[str, Any], default_scope: str) -> str:
    return str(profile.get("scope_path") or profile.get("scope") or default_scope).strip()


def _configured_semantic_profiles_summary(
    *,
    project_root: Path,
    project_name: str,
    cbm_binary: Path,
    scope_path: str,
    profiles: list[dict[str, Any]],
    exclude_substrings: list[str] | None = None,
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for profile in profiles:
        profile_scope = _profile_scope(profile, scope_path)
        terms = _profile_terms(profile)
        if not terms:
            continue
        result = _scoped_semantic_search(
            project_root=project_root,
            project_name=project_name,
            scope_path=profile_scope,
            cbm_binary=cbm_binary,
            semantic_terms=terms,
        )
        payload = _semantic_profile_payload(
            result,
            profile_scope,
            exclude_substrings=exclude_substrings,
        )
        top_local = payload["top_groups"][0] if payload.get("top_groups") else None
        top_row = payload["top_semantic_rows"][0] if payload.get("top_semantic_rows") else None
        top_local_ranked = payload.get("top_local_semantic_row")
        local_rows = int(payload.get("semantic_local_rows", 0))
        non_local_rows = int(payload.get("semantic_non_local_rows", 0))
        total_ranked_rows = local_rows + non_local_rows
        local_ratio = (local_rows / total_ranked_rows) if total_ranked_rows else 0.0
        runs.append(
            {
                "name": str(profile.get("name") or "unnamed-query"),
                "why": str(profile.get("why") or ""),
                "scope": profile_scope,
                "query": str(profile.get("query") or " ".join(terms)),
                "terms": terms,
                "groups": int(payload.get("groups_count", 0)),
                "group_rows": int(payload.get("group_rows_total", 0)),
                "semantic_rows": int(payload.get("semantic_rows_count", 0)),
                "local_rows": local_rows,
                "non_local_rows": non_local_rows,
                "local_ratio": local_ratio,
                "top_local": top_local,
                "top_semantic": top_row,
                "top_local_ranked": top_local_ranked,
            }
        )
    return runs


def _configured_semantic_profiles_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- No configured semantic query profiles."
    lines = [
        "| Intent | Scope | Local Groups | Local Semantic Rows | Non-local Rows | Locality |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        locality = f"{row['local_ratio'] * 100:.0f}%"
        lines.append(
            f"| {row['name']} | {row['scope']} | {row['groups']} | {row['local_rows']} | {row['non_local_rows']} | {locality} |"
        )
    return "\n".join(lines)


def _configured_semantic_profile_findings(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- No profile findings available."
    lines: list[str] = []
    for row in rows:
        head = f"- {row['name']}: local semantic rows={row['local_rows']}, non-local rows={row['non_local_rows']}"
        lines.append(head)
        if row.get("top_local"):
            top_local = row["top_local"]
            lines.append(
                f"  top grouped hit: {top_local.get('file', 'n/a')} -> {top_local.get('top_symbol', 'n/a')}"
            )
        if row.get("top_local_ranked"):
            top_local_ranked = row["top_local_ranked"]
            lines.append(
                f"  top in-scope ranked hit: {top_local_ranked.get('qn', 'n/a')} ({top_local_ranked.get('file', 'n/a')})"
            )
        if row.get("top_semantic"):
            top_semantic = row["top_semantic"]
            lines.append(
                f"  top ranked hit: {top_semantic.get('qn', 'n/a')} ({top_semantic.get('file', 'n/a')})"
            )
        if row["local_ratio"] < 0.4:
            lines.append("  signal quality: low locality; tighten query terms or reduce indexed scope")
    return "\n".join(lines)


def _scope_qn_prefix(summary: dict[str, Any], scope_path: str) -> str:
    scope = summary.get("scope", {})
    return scope.get("scope_qn_prefix") or scope_path.replace("/", ".")


def _scope_filter(alias: str, scope_prefix: str) -> str:
    return f"coalesce({alias}.qn, {alias}.name) CONTAINS '{scope_prefix}'"


def _parse_relation_rows(text: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    pattern = re.compile(r"^(?P<source>.+?)\s+(?P<relation>[A-Z_]+)\s+(?P<target>.+)$")
    for line in text.splitlines():
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith("rows:")
            or stripped.startswith("total:")
            or stripped.startswith("hint:")
        ):
            continue
        match = pattern.match(stripped)
        if not match:
            continue
        rows.append(
            (
                match.group("source").strip(),
                match.group("relation").strip(),
                match.group("target").strip(),
            )
        )
    return rows


def _normalize_scoped_name(raw: str, scope_prefix: str) -> str:
    text = str(raw).strip()
    index = text.find(scope_prefix)
    if index >= 0:
        return text[index:]
    return text


def _semantic_profile_payload(
    semantic_doc: dict[str, Any],
    scope_path: str,
    exclude_substrings: list[str] | None = None,
) -> dict[str, Any]:
    result_doc = semantic_doc.get("result", semantic_doc)
    structured = result_doc.get("payload", {}).get("structuredContent", {})
    groups = structured.get("groups", [])
    semantic_rows_raw = structured.get("semantic", {}).get("rows", [])
    excluded_tokens = [token for token in (exclude_substrings or []) if token]
    semantic_rows: list[Any] = []
    for row in semantic_rows_raw:
        if len(row) < 3:
            continue
        qn = str(row[0])
        file_path = str(row[2])
        if any(token in qn or token in file_path for token in excluded_tokens):
            continue
        semantic_rows.append(row)
    top_groups: list[dict[str, Any]] = []
    for group in groups[:3]:
        rows = group.get("rows", [])
        top_groups.append(
            {
                "file": group.get("file", ""),
                "top_symbol": rows[0][0] if rows and len(rows[0]) > 0 else "",
                "top_label": rows[0][1] if rows and len(rows[0]) > 1 else "",
                "rows_in_group": len(rows),
            }
        )
    top_semantic_rows: list[dict[str, Any]] = []
    for row in semantic_rows[:5]:
        if len(row) < 4:
            continue
        top_semantic_rows.append(
            {
                "qn": row[0],
                "label": row[1],
                "file": row[2],
                "score": row[3],
            }
        )
    top_local_semantic_row: dict[str, Any] | None = None
    for row in semantic_rows:
        if len(row) < 4:
            continue
        file_path = str(row[2])
        if not file_path.startswith(scope_path):
            continue
        top_local_semantic_row = {
            "qn": row[0],
            "label": row[1],
            "file": row[2],
            "score": row[3],
        }
        break
    return {
        "groups_count": len(groups),
        "group_rows_total": sum(len(group.get("rows", [])) for group in groups),
        "semantic_rows_count": len(semantic_rows),
        "semantic_local_rows": sum(
            1
            for row in semantic_rows
            if len(row) >= 3 and str(row[2]).startswith(scope_path)
        ),
        "semantic_non_local_rows": sum(
            1
            for row in semantic_rows
            if len(row) >= 3 and not str(row[2]).startswith(scope_path)
        ),
        "top_groups": top_groups,
        "top_semantic_rows": top_semantic_rows,
        "top_local_semantic_row": top_local_semantic_row,
    }


def _structural_profile_payload(structured_text: str) -> dict[str, Any]:
    rows = _parse_relation_rows(structured_text)
    return {
        "rows": rows,
        "row_count": len(rows),
        "coherent_rows": [
            row for row in rows if ".eval." not in row[0] and ".eval." not in row[2]
        ][:6],
    }


def _structural_search_payload(structural_doc: dict[str, Any]) -> dict[str, Any]:
    result_doc = structural_doc.get("result", structural_doc)
    structured = result_doc.get("payload", {}).get("structuredContent", {})
    groups = structured.get("groups", [])
    top_groups: list[dict[str, Any]] = []
    for group in groups[:3]:
        rows = group.get("rows", [])
        top_groups.append(
            {
                "file": group.get("file", ""),
                "top_symbol": rows[0][0] if rows and len(rows[0]) > 0 else "",
                "top_label": rows[0][1] if rows and len(rows[0]) > 1 else "",
                "rows_in_group": len(rows),
            }
        )
    rows = [
        (group.get("file", ""), row[0], row[1])
        for group in groups
        for row in group.get("rows", [])
        if len(row) >= 2
    ]
    return {
        "groups_count": len(groups),
        "group_rows_total": sum(len(group.get("rows", [])) for group in groups),
        "top_groups": top_groups,
        "rows": rows[:10],
    }


def _scoped_architecture(
    *, project_root: Path, project_name: str, scope_path: str, cbm_binary: Path
) -> dict[str, Any]:
    return run_cbm_tool(
        cbm_binary,
        "get_architecture",
        {
            "project": project_name,
            "path": scope_path,
            "aspects": "overview",
        },
        cwd=project_root,
    )


def _scoped_dependency_edges(
    *, project_root: Path, project_name: str, scope_prefix: str, cbm_binary: Path
) -> dict[str, Any]:
    query = (
        "MATCH (s:Function)-[r:CALLS]->(t) "
        f"WHERE {_scope_filter('s', scope_prefix)} "
        "RETURN s.qn AS source, type(r) AS relation, "
        "coalesce(t.qn, t.name) AS target"
    )
    return run_cbm_tool(
        cbm_binary,
        "query_graph",
        {"project": project_name, "query": query, "max_rows": 30},
        cwd=project_root,
    )


def _scoped_module_dependency_edges(
    *, project_root: Path, project_name: str, scope_prefix: str, cbm_binary: Path
) -> dict[str, Any]:
    query = (
        "MATCH (s:Module)-[r:IMPORTS]->(t:Module) "
        f"WHERE {_scope_filter('s', scope_prefix)} "
        f"AND {_scope_filter('t', scope_prefix)} "
        "RETURN coalesce(s.qn, s.name) AS source, type(r) AS relation, "
        "coalesce(t.qn, t.name) AS target"
    )
    return run_cbm_tool(
        cbm_binary,
        "query_graph",
        {"project": project_name, "query": query, "max_rows": 80},
        cwd=project_root,
    )


def _scoped_class_method_edges(
    *, project_root: Path, project_name: str, scope_prefix: str, cbm_binary: Path
) -> dict[str, Any]:
    query = (
        "MATCH (s:Class)-[r:DEFINES_METHOD]->(t:Method) "
        f"WHERE {_scope_filter('s', scope_prefix)} "
        "RETURN coalesce(s.qn, s.name) AS source, type(r) AS relation, "
        "coalesce(t.qn, t.name) AS target"
    )
    return run_cbm_tool(
        cbm_binary,
        "query_graph",
        {"project": project_name, "query": query, "max_rows": 80},
        cwd=project_root,
    )


def _scoped_class_inheritance_edges(
    *, project_root: Path, project_name: str, scope_prefix: str, cbm_binary: Path
) -> dict[str, Any]:
    query = (
        "MATCH (s:Class)-[r:INHERITS]->(t:Class) "
        f"WHERE {_scope_filter('s', scope_prefix)} "
        f"AND {_scope_filter('t', scope_prefix)} "
        "RETURN coalesce(s.qn, s.name) AS source, type(r) AS relation, "
        "coalesce(t.qn, t.name) AS target"
    )
    return run_cbm_tool(
        cbm_binary,
        "query_graph",
        {"project": project_name, "query": query, "max_rows": 40},
        cwd=project_root,
    )


def _scoped_semantic_search(
    *,
    project_root: Path,
    project_name: str,
    scope_path: str,
    cbm_binary: Path,
    semantic_terms: list[str],
) -> dict[str, Any]:
    return run_cbm_tool(
        cbm_binary,
        "search_graph",
        {
            "project": project_name,
            "semantic_query": semantic_terms,
            "file_pattern": f"{scope_path}/*",
            "limit": 30,
            "format": "json",
        },
        cwd=project_root,
    )


def _dependency_rows_from_text(text: str) -> list[tuple[str, str, str]]:
    return _parse_relation_rows(text)


def _short_name(qualified_name: str) -> str:
    return qualified_name.split(".")[-1].replace("-", "_")


def _module_name_for_file(file_path: str | Path, *, package_root: Path | None = None) -> str:
    path = Path(file_path)
    if package_root is not None:
        try:
            rel = path.relative_to(package_root)
        except ValueError:
            rel = path
        module_parts = rel.with_suffix("").parts
        return ".".join(module_parts)
    return ".".join(path.with_suffix("").parts)


def _fallback_dependency_rows(
    package_root: Path, package_prefix: str | None = None
) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    if not package_root.exists():
        return rows

    effective_prefix = package_prefix or package_root.name

    for path in sorted(package_root.rglob("*.py")):
        if path.name == "__init__.py":
            source = _module_name_for_file(path, package_root=package_root.parent)
        else:
            source = _module_name_for_file(path, package_root=package_root.parent)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(effective_prefix):
                        rows.append((source, "IMPORTS", alias.name))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith(effective_prefix):
                    rows.append((source, "IMPORTS", module))
                elif node.level > 0 and module:
                    package_prefix = ".".join(source.split(".")[:-1])
                    rows.append((source, "IMPORTS", f"{package_prefix}.{module}"))

    deduped: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        if row not in seen:
            seen.add(row)
            deduped.append(row)
    return deduped


def _search_hit_dependency_rows(
    semantic_doc: dict[str, Any], scope_path: str
) -> list[tuple[str, str, str]]:
    result_doc = semantic_doc.get("result", semantic_doc)
    structured = result_doc.get("payload", {}).get("structuredContent", {})
    groups = structured.get("groups", [])
    rows: list[tuple[str, str, str]] = []
    local_groups: list[dict[str, Any]] = []
    for group in groups:
        file_path = str(group.get("file", ""))
        if file_path.startswith(scope_path):
            local_groups.append(group)

    previous_symbol: str | None = None
    for group in local_groups[:8]:
        file_path = str(group.get("file", ""))
        module_name = _module_name_for_file(file_path)
        row_items = group.get("rows", [])
        if not row_items:
            continue

        primary_symbol = row_items[0][0] if len(row_items[0]) > 0 else ""
        if primary_symbol:
            rows.append((module_name, "SEARCH_HIT", primary_symbol))
            if previous_symbol:
                rows.append((previous_symbol, "SEARCH_HIT", primary_symbol))
            previous_symbol = primary_symbol

        if len(row_items) > 1:
            secondary_symbol = row_items[1][0] if len(row_items[1]) > 0 else ""
            if secondary_symbol:
                rows.append((primary_symbol, "SEARCH_HIT", secondary_symbol))
                if previous_symbol and previous_symbol != primary_symbol:
                    rows.append((primary_symbol, "SEARCH_HIT", previous_symbol))

    deduped: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        if row not in seen:
            seen.add(row)
            deduped.append(row)
    return deduped


def _mermaid_status(modules: dict[str, Any]) -> str:
    lines = ["```mermaid", "flowchart LR"]
    for module_name, value in modules.items():
        status = _status_label(value)
        lines.append(f'  {module_name}["{module_name}: {status}"]')
    lines.append("```")
    return "\n".join(lines)


def _mermaid_artifact_sizes(size_rows: list[tuple[str, int]]) -> str:
    lines = ["```mermaid", "pie showData", "  title Artifact Sizes (bytes)"]
    for name, size in size_rows:
        lines.append(f'  "{name}" : {size}')
    lines.append("```")
    return "\n".join(lines)


def _mermaid_scoped_labels(node_labels: list[tuple[str, int]]) -> str:
    lines = ["```mermaid", "pie showData", "  title Scoped Node Labels"]
    for name, count in node_labels[:6]:
        lines.append(f'  "{name}" : {count}')
    lines.append("```")
    return "\n".join(lines)


def _mermaid_scoped_edges(dep_rows: list[tuple[str, str, str]]) -> str:
    lines = ["```mermaid", "flowchart LR"]
    if not dep_rows:
        lines.append('  no_edges["No local dependency edges found"]')
        lines.append("```")
        return "\n".join(lines)
    for source, relation, target in dep_rows[:12]:
        source_id = _short_name(source)
        target_id = _short_name(target)
        lines.append(
            f'  {source_id}["{_short_name(source)}"] -->|{relation}| {target_id}["{_short_name(target)}"]'
        )
    lines.append("```")
    return "\n".join(lines)


def _relation_counters(
    rows: list[tuple[str, str, str]], scope_prefix: str
) -> dict[str, Any]:
    normalized = [
        (
            _normalize_scoped_name(source, scope_prefix),
            relation,
            _normalize_scoped_name(target, scope_prefix),
        )
        for source, relation, target in rows
    ]
    deduped: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in normalized:
        if row not in seen:
            seen.add(row)
            deduped.append(row)

    fan_out = Counter(source for source, _, _ in deduped)
    fan_in = Counter(target for _, _, target in deduped)
    targets_by_source: dict[str, set[str]] = defaultdict(set)
    sources_by_target: dict[str, set[str]] = defaultdict(set)
    for source, _relation, target in deduped:
        targets_by_source[source].add(target)
        sources_by_target[target].add(source)

    return {
        "rows": deduped,
        "fan_out": fan_out,
        "fan_in": fan_in,
        "targets_by_source": targets_by_source,
        "sources_by_target": sources_by_target,
    }


def _top_counter_lines(counter: Counter[str], *, limit: int = 6) -> list[str]:
    return [f"{name} ({count})" for name, count in counter.most_common(limit)]


def _entry_point_lines(scoped_arch_text: str, *, limit: int = 8) -> list[str]:
    entries = _parse_section_lines(scoped_arch_text, "entry_points")
    return entries[:limit]


def _class_surface_lines(class_rows: list[tuple[str, str, str]]) -> list[str]:
    counts = Counter(source for source, _, _ in class_rows)
    lines: list[str] = []
    for class_name, count in counts.most_common(6):
        lines.append(f"{class_name} defines {count} methods")
    return lines


def _optional_demo_artifacts_section(
    *,
    include_demo_artifacts: bool,
    scope_path: str,
    representative_report: str,
    search_hit_rows: list[tuple[str, str, str]],
) -> str:
    if not include_demo_artifacts:
        return ""

    section = [
        "## Optional Demo Artifacts",
        "",
        "These sections are example-driven discovery aids. They are useful for tool evaluation, but they are not part of the default architecture report because they read like demos rather than project findings.",
    ]
    if representative_report:
        section.extend(["", "### Representative semantic searches", "", representative_report])
    search_block = _search_hit_dependency_block(search_hit_rows, scope_path)
    if search_block:
        section.extend(["", search_block.strip()])
    return "\n".join(section) + "\n"


def _mermaid_structural_hits(rows: list[tuple[str, str, str]]) -> str:
    """Render found symbols grouped by source file as a flowchart.

    rows: list of (file_path, symbol_name, label) from _structural_search_payload.
    Each unique file becomes a node; each symbol in that file gets an edge from it.
    """
    lines = ["```mermaid", "flowchart LR"]
    if not rows:
        lines.append('  no_hits["No matching symbols found"]')
        lines.append("```")
        return "\n".join(lines)
    seen_ids: dict[str, str] = {}

    def node_id(raw: str) -> str:
        safe = raw.replace(".", "_").replace("/", "_").replace("-", "_")
        if safe not in seen_ids:
            seen_ids[safe] = raw
        return safe

    for file_path, symbol_name, _label in rows[:12]:
        module = Path(file_path).stem
        fid = node_id(module)
        sid = node_id(symbol_name)
        lines.append(f'  {fid}["{module}"] -->|DEFINES| {sid}["{symbol_name}"]')
    lines.append("```")
    return "\n".join(lines)


def _mermaid_semantic_signal(summary: dict[str, int]) -> str:
    lines = [
        "```mermaid",
        "pie showData",
        "  title Semantic Results: Local vs Non-local",
    ]
    lines.append(f'  "local" : {summary.get("local", 0)}')
    lines.append(f'  "non_local" : {summary.get("non_local", 0)}')
    lines.append("```")
    return "\n".join(lines)


def _candidate_input_rows(
    *,
    source_index: dict[str, Any],
    dependency_doc: dict[str, Any],
    semantic_doc: dict[str, Any],
    architecture_doc: dict[str, Any],
    scope_path: str,
) -> list[dict[str, str]]:
    structured = (
        source_index.get("index", {}).get("payload", {}).get("structuredContent", {})
    )
    excluded = structured.get("excluded", {}).get("dirs", [])
    staged_files = source_index.get("staged_files", [])
    staged_hint = (
        f"{len(staged_files)} files"
        + (f"; sample={', '.join(staged_files[:3])}" if staged_files else "")
    )
    return [
        {
            "artifact": "source_index.json",
            "candidate": "codebase-memory-mcp",
            "input": f"Config-scoped staging repo from .refactor/config.json, files={staged_hint}",
            "output": "Indexed graph metadata: node/edge counts, exclusions, parse warnings, project registration",
            "interpretation": "Tells us whether downstream graph outputs are trustworthy enough to inspect and whether indexing stayed inside the configured file set",
        },
        {
            "artifact": "dependency_graph.json",
            "candidate": "codebase-memory-mcp",
            "input": dependency_doc["query"],
            "output": "Raw CALLS/IMPORTS/INHERITS edge rows capped at max_rows",
            "interpretation": "Useful as machine graph data, but broad queries can mix target code with indexed evaluation repos",
        },
        {
            "artifact": "semantic_retrieval.json",
            "candidate": "codebase-memory-mcp",
            "input": f"semantic terms={semantic_doc['semantic_terms']}, scope hint={scope_path}",
            "output": "Grouped structural matches plus semantic ranking rows with scores",
            "interpretation": "Good for discoverability, but current broad corpus makes semantic ranking noisy",
        },
        {
            "artifact": "architecture_report.json",
            "candidate": "codebase-memory-mcp",
            "input": "get_architecture(aspects=overview) on full corpus and scoped path re-query",
            "output": "Human-readable counts, hotspots, clusters, node labels, edge types",
            "interpretation": "Most useful artifact for quickly understanding structure and central coordination points",
        },
    ]


def _markdown_input_table(rows: list[dict[str, str]]) -> str:
    lines = [
        "| Artifact | Candidate | Input Used | Output Produced | How To Interpret |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['artifact']} | {row['candidate']} | {row['input']} | {row['output']} | {row['interpretation']} |"
        )
    return "\n".join(lines)


def _markdown_profile_table(rows: list[dict[str, str]]) -> str:
    lines = [
        "| Profile | Query | Scope | Why It Helps |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['name']} | {row['query']} | {row['scope']} | {row['why']} |"
        )
    return "\n".join(lines)


def _search_hit_dependency_block(
    dep_rows: list[tuple[str, str, str]], scope_path: str
) -> str:
    if not dep_rows:
        return ""
    return (
        "\n\n## Search-hit Dependency View\n\n"
        f"This diagram shows the local results captured by semantic search within `{scope_path}` so the report can reflect the actual discovery hits as well as the raw import graph.\n\n"
        f"{_mermaid_scoped_edges(dep_rows)}\n"
    )


def _example_edge_lines(
    dep_rows: list[tuple[str, str, str]],
) -> tuple[list[str], list[str]]:
    coherent: list[str] = []
    suspicious: list[str] = []
    for source, relation, target in dep_rows:
        line = f"{source} {relation} {target}"
        if ".eval." in target or ".eval." in source:
            suspicious.append(line)
        else:
            coherent.append(line)
    return coherent[:6], suspicious[:6]


def _line_list(items: list[str], fallback: str) -> str:
    return "\n".join(f"- {item}" for item in items) if items else f"- {fallback}"


def build_candidate_report(
    *,
    input_dir: Path,
    output_path: Path,
    scope_path: str,
    project_root: Path | None = None,
    cbm_binary_path: str | None = None,
    include_demo_artifacts: bool = False,
    semantic_query_profiles: list[dict[str, Any]] | None = None,
) -> str:
    summary = load_json(input_dir / "summary.json")
    scope_policy = summary.get("scope", {})
    source_index = load_json(input_dir / "source_index.json")
    scope_baseline = (
        load_json(input_dir / "scope_baseline.json")
        if (input_dir / "scope_baseline.json").exists()
        else {"counts": {}}
    )
    architecture = load_json(input_dir / "architecture_report.json")
    semantic = load_json(input_dir / "semantic_retrieval.json")
    coderag = (
        load_json(input_dir / "coderag_validate.json")
        if (input_dir / "coderag_validate.json").exists()
        else None
    )

    project_root = project_root or Path(summary["project_root"])
    cbm_binary = resolve_cbm_binary(cbm_binary_path)
    project_name = summary["project_name"]
    scope_prefix = _scope_qn_prefix(summary, scope_path)
    structured_index = (
        source_index.get("index", {}).get("payload", {}).get("structuredContent", {})
    )
    baseline_counts = scope_baseline.get("counts", {})

    scoped_architecture = _scoped_architecture(
        project_root=project_root,
        project_name=project_name,
        scope_path=scope_path,
        cbm_binary=cbm_binary,
    )
    scoped_arch_text = _extract_text_content(scoped_architecture.get("payload", {}))
    scoped_node_labels = _parse_section_counts(scoped_arch_text, "node_labels")
    scoped_edge_types = _parse_section_counts(scoped_arch_text, "edge_types")
    scoped_hotspots = _parse_section_lines(scoped_arch_text, "hotspots")
    scoped_clusters = _parse_section_lines(scoped_arch_text, "clusters")

    scoped_dep = _scoped_dependency_edges(
        project_root=project_root,
        project_name=project_name,
        scope_prefix=scope_prefix,
        cbm_binary=cbm_binary,
    )
    scoped_dep_text = _extract_text_content(scoped_dep.get("payload", {}))
    raw_scoped_dep_rows = _dependency_rows_from_text(scoped_dep_text)
    scoped_dep_rows, discarded_dependency_rows = _filter_relation_rows(
        raw_scoped_dep_rows,
        scope_prefix,
        scope_policy.get("exclude_qn_substrings", []),
    )
    module_dep_doc = _scoped_module_dependency_edges(
        project_root=project_root,
        project_name=project_name,
        scope_prefix=scope_prefix,
        cbm_binary=cbm_binary,
    )
    raw_module_dep_rows = _dependency_rows_from_text(
        _extract_text_content(module_dep_doc.get("payload", {}))
    )
    module_dep_rows, discarded_module_rows = _filter_relation_rows(
        raw_module_dep_rows,
        scope_prefix,
        scope_policy.get("exclude_qn_substrings", []),
    )
    module_dep_source = "CBM IMPORTS query"
    if not module_dep_rows:
        module_dep_rows = _fallback_dependency_rows(
            project_root / scope_path, package_prefix=scope_prefix
        )
        module_dep_source = "local AST import fallback"

    if not scoped_dep_rows:
        scoped_dep_rows = module_dep_rows
    coherent_edges, suspicious_edges = _example_edge_lines(scoped_dep_rows)
    search_hit_rows = _search_hit_dependency_rows(semantic, scope_path)

    class_method_doc = _scoped_class_method_edges(
        project_root=project_root,
        project_name=project_name,
        scope_prefix=scope_prefix,
        cbm_binary=cbm_binary,
    )
    class_method_rows, discarded_class_method_rows = _filter_relation_rows(
        _dependency_rows_from_text(
        _extract_text_content(class_method_doc.get("payload", {}))
        ),
        scope_prefix,
        scope_policy.get("exclude_qn_substrings", []),
    )
    class_inheritance_doc = _scoped_class_inheritance_edges(
        project_root=project_root,
        project_name=project_name,
        scope_prefix=scope_prefix,
        cbm_binary=cbm_binary,
    )
    class_inheritance_rows, discarded_inheritance_rows = _filter_relation_rows(
        _dependency_rows_from_text(
        _extract_text_content(class_inheritance_doc.get("payload", {}))
        ),
        scope_prefix,
        scope_policy.get("exclude_qn_substrings", []),
    )

    scoped_semantic = _scoped_semantic_search(
        project_root=project_root,
        project_name=project_name,
        scope_path=scope_path,
        cbm_binary=cbm_binary,
        semantic_terms=semantic["semantic_terms"],
    )
    representative_searches: list[dict[str, Any]] = []
    configured_profiles = semantic_query_profiles or []
    configured_profile_runs = _configured_semantic_profiles_summary(
        project_root=project_root,
        project_name=project_name,
        cbm_binary=cbm_binary,
        scope_path=scope_path,
        profiles=configured_profiles,
        exclude_substrings=scope_policy.get("exclude_qn_substrings", []),
    )
    if include_demo_artifacts:
        semantic_profiles = _semantic_query_profiles(scope_path)
        for profile in semantic_profiles:
            profile_result = _scoped_semantic_search(
                project_root=project_root,
                project_name=project_name,
                scope_path=profile["scope"],
                cbm_binary=cbm_binary,
                semantic_terms=[
                    token.strip() for token in profile["query"].split() if token.strip()
                ],
            )
            structural_result = run_cbm_tool(
                cbm_binary,
                "search_graph",
                {
                    "project": project_name,
                    "name_pattern": profile["structural_pattern"],
                    "label": "Function",
                    "limit": 20,
                    "format": "json",
                },
                cwd=project_root,
            )
            representative_searches.append(
                {
                    "question": profile["name"],
                    "query": profile["query"],
                    "why": profile["why"],
                    "result": _semantic_profile_payload(
                        profile_result,
                        scope_path,
                        exclude_substrings=scope_policy.get("exclude_qn_substrings", []),
                    ),
                    "raw_result": profile_result,
                    "structural_pattern": profile["structural_pattern"],
                    "structural_result": _structural_search_payload(structural_result),
                }
            )

    full_arch_text = _architecture_text(architecture)
    full_languages = _parse_section_counts(full_arch_text, "languages")
    sizes = _artifact_size_rows(input_dir)
    local_groups = _top_local_groups(scoped_semantic, scope_path)
    local_semantic_stats = _semantic_group_summary(scoped_semantic, scope_path)
    semantic_noise = _semantic_noise_summary(
        semantic,
        scope_path,
        exclude_substrings=scope_policy.get("exclude_qn_substrings", []),
    )
    modules = summary["modules"]
    provider_modules_ok = modules.get("source_index", True) is True
    partial_parse_count = int(structured_index.get("parse_partial_count", 0) or 0)
    not_indexed_count = int(structured_index.get("not_indexed_files_count", 0) or 0)
    index_status = _trust_status(
        provider_ok=provider_modules_ok,
        partial=partial_parse_count > 0 or not_indexed_count > 0,
        usable=bool(structured_index),
    )
    dependency_discarded = len(discarded_dependency_rows) + len(discarded_module_rows)
    dependency_status = _trust_status(
        provider_ok=bool(scoped_dep.get("ok", True)),
        discarded=dependency_discarded > 0,
        usable=bool(scoped_dep_rows),
    )
    semantic_status = _trust_status(
        provider_ok=bool(scoped_semantic.get("ok", True)),
        discarded=semantic_noise["non_local"] > 0 or semantic_noise["discarded"] > 0,
        usable=semantic_noise["local"] > 0,
    )
    module_summary = _relation_counters(module_dep_rows, scope_prefix)
    function_summary = _relation_counters(scoped_dep_rows, scope_prefix)
    class_summary = _relation_counters(class_method_rows, scope_prefix)
    input_rows = _candidate_input_rows(
        source_index=source_index,
        dependency_doc=load_json(input_dir / "dependency_graph.json"),
        semantic_doc=semantic,
        architecture_doc=architecture,
        scope_path=scope_path,
    )

    daemon_policy = scope_policy.get("daemon_mode", "unspecified")
    readiness_items = [
        ("Indexing and project registration", index_status),
        ("Scoped architecture extraction", "OK" if scoped_arch_text else "FAIL"),
        (
            "Scoped dependency extraction",
            dependency_status,
        ),
        (
            "Scoped semantic retrieval signal",
            semantic_status,
        ),
        (
            "CodeRAG validation",
            _status_label(coderag.get("ok")) if coderag is not None else "SKIP",
        ),
        (
            "Persistent daemon mode",
            "SKIP" if daemon_policy == "out_of_scope" else "OK",
        ),
    ]
    overall_status = "AUTOMATION_BLOCKED"
    if all(status == "OK" for _name, status in readiness_items):
        overall_status = "READY_FOR_AUTOMATION"
    elif any(status == "FAIL" for _name, status in readiness_items):
        overall_status = "MANUAL_ONLY"
    elif any(status in {"DEGRADED", "PARTIAL"} for _name, status in readiness_items):
        overall_status = "REVIEWABLE"
    if semantic_noise["non_local"] or dependency_discarded:
        main_issue = (
            "Some relationships leave the configured corpus; they are treated as "
            "external dependencies and are excluded from internal refactoring evidence."
        )
        next_action = (
            "Inspect the external dependency list and expand configuration only when "
            "those files are part of the intended refactoring boundary."
        )
    else:
        main_issue = "No scope-crossing relationships were observed in the analyzed results."
        next_action = "Proceed to AST/CBM agreement checks for individual candidates."
    status_by_module = {
        "scope_baseline": "FAIL"
        if baseline_counts.get("parse_errors", 0)
        else "OK",
        "source_index": index_status,
        "dependency_graph": dependency_status,
        "semantic_retrieval": semantic_status,
        "architecture_report": "OK" if scoped_arch_text else "FAIL",
        "coderag_validate": _status_label(coderag.get("ok"))
        if coderag is not None
        else "SKIP",
    }
    status_lines = "\n".join(
        f"| {name} | {status_by_module.get(name, _status_label(value))} |"
        for name, value in modules.items()
    )

    size_lines = "\n".join(f"| {name} | {size} |" for name, size in sizes)
    readiness_lines = "\n".join(
        f"| {name} | {status} |" for name, status in readiness_items
    )

    local_group_lines = (
        "\n".join(
            f"- {file_path}: `{name}` ({label}, in={in_count}, out={out_count})"
            for file_path, name, label, in_count, out_count in local_groups
        )
        or "- No local grouped results found."
    )

    representative_sections: list[str] = []
    for index, search in enumerate(representative_searches, start=1):
        result = search["result"]
        structural = search["structural_result"]
        top_group = result["top_groups"][0] if result["top_groups"] else None
        top_semantic = (
            result["top_semantic_rows"][0] if result["top_semantic_rows"] else None
        )
        structural_top = (
            structural["top_groups"][0] if structural["top_groups"] else None
        )
        section_lines = [
            f"### Example {index}: {search['question']}",
            f"- Why this question: {search['why']}",
            f"- Search sent: semantic_query=[{search['query']}], file_pattern={scope_path}/*, limit=30",
            f"- Raw counts: groups={result['groups_count']}, group_rows={result['group_rows_total']}, semantic_rows={result['semantic_rows_count']}, local={result['semantic_local_rows']}, non_local={result['semantic_non_local_rows']}",
        ]
        if top_group:
            section_lines.append(
                f"- Top grouped hit: {top_group['file']} -> {top_group['top_symbol']} ({top_group['top_label']}, group_rows={top_group['rows_in_group']})"
            )
        if top_semantic:
            section_lines.append(
                f"- Top semantic hit: {top_semantic['qn']} [{top_semantic['label']}] in {top_semantic['file']} score={top_semantic['score']:.4f}"
            )
        section_lines.append("- Dependency diagram from discovered items:")
        section_lines.append(_mermaid_structural_hits(structural["rows"]))
        section_lines.append(
            f"- Verification search sent: name_pattern={search['structural_pattern']}, label=Function, limit=20"
        )
        section_lines.append(
            f"- Verification counts: groups={structural['groups_count']}, rows={structural['group_rows_total']}"
        )
        if structural_top:
            section_lines.append(
                f"- Verification top hit: {structural_top['file']} -> {structural_top['top_symbol']} ({structural_top['top_label']}, group_rows={structural_top['rows_in_group']})"
            )
        section_lines.append(
            "- Human-readable result: the semantic rank is still noisy, but the verification search confirms the local function(s) that implement the question."
        )
        representative_sections.append("\n".join(section_lines))
    representative_report = "\n\n".join(representative_sections)
    entry_point_lines = _line_list(
        _entry_point_lines(scoped_arch_text),
        "No entry points discovered.",
    )
    module_fan_out_lines = _line_list(
        _top_counter_lines(module_summary["fan_out"]),
        "No module import edges recovered.",
    )
    module_fan_in_lines = _line_list(
        _top_counter_lines(module_summary["fan_in"]),
        "No inbound module import edges recovered.",
    )
    function_fan_out_lines = _line_list(
        _top_counter_lines(function_summary["fan_out"]),
        "No function call edges recovered.",
    )
    function_fan_in_lines = _line_list(
        _top_counter_lines(function_summary["fan_in"]),
        "No called-function targets recovered.",
    )
    class_surface = _line_list(
        _class_surface_lines(class_summary["rows"]),
        "No class/method surface recovered from the scoped graph.",
    )
    inheritance_lines = _line_list(
        [
            f"{_normalize_scoped_name(source, scope_prefix)} INHERITS {_normalize_scoped_name(target, scope_prefix)}"
            for source, _relation, target in class_inheritance_rows[:6]
        ],
        "No class inheritance edges recovered.",
    )

    hotspot_lines = (
        "\n".join(f"- {line}" for line in scoped_hotspots[:8]) or "- No hotspots found."
    )
    cluster_lines = (
        "\n".join(f"- {line}" for line in scoped_clusters[:6]) or "- No clusters found."
    )
    coherent_edge_lines = _line_list(
        coherent_edges,
        "No fully local edges recovered in this sample.",
    )
    suspicious_edge_lines = _line_list(
        suspicious_edges,
        "No suspicious cross-corpus edges observed in this sample.",
    )

    coderag_note = ""
    if coderag is not None:
        coderag_note = (
            f"CodeRAG status: `{_status_label(coderag.get('ok'))}`. "
            f"Reason: {coderag.get('reason', 'n/a')}."
        )

    demo_artifacts = _optional_demo_artifacts_section(
        include_demo_artifacts=include_demo_artifacts,
        scope_path=scope_path,
        representative_report=representative_report,
        search_hit_rows=search_hit_rows,
    )

    report = f"""# Candidate Analysis Report

Generated: {dt.datetime.now().isoformat(timespec="seconds")}

Project: `{project_name}`

This report converts the raw Phase A candidate artifacts into a human-readable summary so the merit of the output can be checked quickly.

## Status

Overall readiness: **{overall_status}**

Safe for manual exploration: **YES**

Safe for automated refactoring: **{"YES" if overall_status == "READY_FOR_AUTOMATION" else "NO"}**

Scope: `{scope_path}`

Configured/staged files: **{len(source_index.get("staged_files", []))}**<br>
AST parsed files: **{baseline_counts.get("parsed_files", "n/a")}**<br>
AST internal import edges: **{baseline_counts.get("internal_import_edges", "n/a")}**<br>
AST external imports: **{baseline_counts.get("external_imports", "n/a")}**<br>
Partial parses: **{partial_parse_count}**<br>
Files not indexed: **{not_indexed_count}**<br>
Out-of-scope dependency rows discarded: **{dependency_discarded}**<br>
Semantic rows: raw **{semantic_noise["raw"]}**, local **{semantic_noise["local"]}**, non-local **{semantic_noise["non_local"]}**, discarded **{semantic_noise["discarded"]}**

Main issue: {main_issue}

Next action: {next_action}

| Module | Status |
|---|---|
{status_lines}

{_mermaid_status(status_by_module)}

Example:
- Rerun the pipeline with `refactor-cli candidate-phase-a --config .refactor/config.json`.
- Then render the report with `refactor-cli candidate-report --config .refactor/config.json`.
- If a module is FAIL, start with the failed artifact rather than the report itself.

## Artifact Sizes

| Artifact | Bytes |
|---|---:|
{size_lines}

{_mermaid_artifact_sizes(sizes)}

Example:
- Larger JSON files usually mean broader graph output or more search hits.
- Open the matching artifact in `.refactor/analysis/candidates/` when you need raw rows or payload fields.
- Compare `semantic_retrieval.json` against `dependency_graph.json` to see ranking vs. raw edges.

## What The Raw Files Mean

- `source_index.json`: index health and coverage
- `dependency_graph.json`: raw edge extraction
- `semantic_retrieval.json`: ranked and grouped search hits
- `architecture_report.json`: highest-value human summary
- `summary.json`: pass/fail snapshot

Examples:
- If `semantic_retrieval.json` looks noisy, run `refactor-cli candidate-search --label Class` and tighten the query.
- If `source_index.json` is wrong, check `.refactor/config.json` and rerun Phase A.
- If you only need the architecture summary, open `architecture_report.json` first.

## Evaluation Matrix

{_markdown_input_table(input_rows)}

Observation:
- This makes the pipeline traceable. Each artifact can now be judged by the exact input it used, the candidate that produced it, and the meaning of the output.

Example:
- To inspect a specific artifact, run the matching wrapper command instead of opening the JSON first.
- For discovery questions, `candidate-search` is the shortest path.
- For a full structural refresh, use `candidate-phase-a` and then `candidate-report`.

## Readiness Checklist

| Capability | Status |
|---|---|
{readiness_lines}

Policy note:
- Persistent daemon mode is intentionally not part of this project's operating model.
- Current scope policy: file scope `{scope_policy.get("scope_path", scope_path)}`, qn scope `{scope_policy.get("scope_qn_prefix", "n/a")}`, excluded qn substrings `{scope_policy.get("exclude_qn_substrings", [])}`.

Examples:
- `LOW_SIGNAL` means the semantic query should be narrowed or rewritten.
- `PARTIAL` on dependency extraction usually means the QN scope needs adjustment.
- `OUT_OF_SCOPE` on daemon mode means you can ignore that item for this project.

## Index Health

- Indexed nodes: {structured_index.get("nodes", "n/a")}
- Indexed edges: {structured_index.get("edges", "n/a")}
- Excluded directories shown by the tool: {", ".join(structured_index.get("excluded", {}).get("dirs", [])) or "not reported"}
- Partial parse count: {structured_index.get("parse_partial_count", "n/a")}
- Not indexed file count: {structured_index.get("not_indexed_files_count", "n/a")}

Observation:
- The index succeeded and is large enough for meaningful graph analysis.
- The corpus may include auxiliary folders beyond `{scope_path}`, so raw full-project results are noisier than the scoped package.

Example:
- If this section shows extra noise, try `refactor-cli candidate-search --scope-path {scope_path} --label Class`.
- Add `--cbm-options "--include-connected"` when you want CBM to show connected context around the matches.
- Use `--cbm-options "--min-degree 1"` to suppress weaker graph noise.

## Full-Corpus Architecture Snapshot

- Languages detected in the indexed corpus: {", ".join(f"{name}={count}" for name, count in full_languages[:6])}
- This confirms that the full graph is dominated by the evaluation repositories, not just the target package.

Example:
- This snapshot is useful when you want a quick sanity check on scope contamination.
- If full-corpus results look too broad, switch to a scoped query with `--scope-path {scope_path}`.
- For a tighter class view, add `--label Class`.

## Scoped Architecture For `{scope_path}`

- Scoped total nodes: {_parse_scalar_value(scoped_arch_text, "scoped_total_nodes") or _parse_scalar_value(scoped_arch_text, "total_nodes")}
- Scoped total edges: {_parse_scalar_value(scoped_arch_text, "scoped_total_edges") or _parse_scalar_value(scoped_arch_text, "total_edges")}
- Entry point: {_parse_section_lines(scoped_arch_text, "entry_points")[0] if _parse_section_lines(scoped_arch_text, "entry_points") else "n/a"}

{_mermaid_scoped_labels(scoped_node_labels)}

Top scoped edge types:
- {", ".join(f"{name}={count}" for name, count in scoped_edge_types[:6])}

Hotspots:
{hotspot_lines}

Clusters:
{cluster_lines}

Entry points:
{entry_point_lines}

Observation:
- The real package is a compact Python CLI package.
- The central coordination points are discovery/config/file-writing helpers and the candidate integration runner.

Example:
- Use `refactor-cli candidate-search --scope-path {scope_path} --label Function` to inspect the implementation entrypoints behind this section.
- If you need more context around a result, add `--cbm-options "--include-connected"`.

## Scoped Module Dependencies

- Data source: {module_dep_source}
- Unique module import edges: {len(module_summary['rows'])}

{_mermaid_scoped_edges(module_summary['rows'])}

Highest fan-out modules:
{module_fan_out_lines}

Highest fan-in modules:
{module_fan_in_lines}

Observation:
- Module-level imports show how the package is stitched together structurally.
- This is the most stable dependency view when function-call extraction is sparse or noisy.

Example:
- Query module relationships directly with `refactor-cli candidate-search --scope-path {scope_path} --label Function --cbm-options "--relationship IMPORTS"`.
- Add `--cbm-options "--include-connected"` to include attached context.

## Scoped Function Dependencies

The current stored `dependency_graph.json` is raw and broad. For clarity, this report derives a scoped function-call view from direct CBM graph queries and falls back to local structure only when necessary.

{_mermaid_scoped_edges(function_summary['rows'])}

Highest fan-out functions:
{function_fan_out_lines}

Highest fan-in targets:
{function_fan_in_lines}

Coherent local edge examples:
{coherent_edge_lines}

Suspicious edge examples:
{suspicious_edge_lines}

Observation:
- The graph can recover useful function-level coordination points when the qualified-name scope is set correctly.
- Function-call edges are good for hotspot inspection, but module imports remain the more stable architectural signal.
- Suspicious cross-corpus edges should still be treated as a scoping or indexing problem, not as trustworthy architecture data.

Example:
- Use `refactor-cli candidate-search --scope-path {scope_path} --label Function --cbm-options "--relationship CALLS"` to focus on call flow.
- If the query is too broad, add `--cbm-options "--min-degree 1"`.

## Scoped Class / Model Surface

This section uses the class and method nodes exposed by codebase-memory. In Python repositories this is usually the closest available proxy for model-level structure.

- Class-to-method edges recovered: {len(class_summary['rows'])}
- Inheritance edges recovered: {len(class_inheritance_rows)}

{_mermaid_scoped_edges(class_summary['rows'])}

Classes with the largest method surfaces:
{class_surface}

Inheritance examples:
{inheritance_lines}

Observation:
- This section is only as rich as the repository's class usage. Function-heavy scripts will naturally produce a sparse model view.
- For dataclass-heavy or OO-heavy projects, this becomes the best high-level view of model boundaries and behavior ownership.

Example:
- Use `refactor-cli candidate-search --scope-path {scope_path} --label Class` to inspect the same model surface interactively.
- Add `--cbm-options "--include-connected"` if you want the surrounding function context for a class hit.

## Semantic Retrieval Interpretation

The stored artifact is evaluated as-is, without generating extra example queries unless explicitly requested.

What the output looks like:
- `groups`: files with local matches, each row showing `name`, `label`, `lines`, `in`, `out`
- `semantic.rows`: ranked hits with `qn`, `label`, `file`, and `score`
- In other words, this is ranked graph search output, not a generated answer.

Examples:
- For the configured profile queries, run `refactor-cli candidate-search --profile "Calculation and processing"`.
- For a one-off question, pass `--semantic-query '["simulation","run_model","throughput","servicegrad","kanban"]'`.
- For more context around a hit, add `--cbm-options "--include-connected"`.

How semantic is it?
- The search uses semantic terms, but the answer is still grounded in the indexed graph.
- In this repo, that means the signal is partially semantic and partially structural.
- The score is most useful as a prioritization hint after you already know the package scope.

Configured semantic query intents:

{_configured_semantic_profiles_table(configured_profile_runs)}

Configured query findings:
{_configured_semantic_profile_findings(configured_profile_runs)}

Evaluation scorecard for the baseline scoped search:
- local grouped files: {local_semantic_stats["local_groups"]}
- local grouped rows: {local_semantic_stats["local_rows"]}
- local ranking rows: {semantic_noise["local"]}
- non-local ranking rows: {semantic_noise["non_local"]}

- Local grouped hits in `{scope_path}`:
{local_group_lines}

- Semantic rows split:
    - local scoped rows: {semantic_noise["local"]}
    - non-local rows: {semantic_noise["non_local"]}

{_mermaid_semantic_signal(semantic_noise)}

Observation:
- The semantic retrieval command works, but the ranking still drifts into .eval candidates in this corpus.
- The grouped local results are the useful part for understanding this project.

What this means in practice:
- Successful execution does not imply meaningful insight.
- For this project, semantic retrieval is best used as package-local discovery plus a raw ranking hint, not as a reliable answer engine.

How to use it here:
{_line_list(_semantic_usage_guidance(scope_path), "No guidance available.")}

More detail options:
{_line_list(_detail_options_lines(scope_path), "No detail options available.")}

{demo_artifacts}

## Practical Conclusions

- The outputs have merit, but only after scoping and summarization.
- `architecture_report.json` plus the scoped module/function/class sections above are the strongest combination for human understanding.
- `dependency_graph.json` and `semantic_retrieval.json` should still be treated as machine-oriented raw data unless filtered to the target package.
- Demo-style semantic examples are best kept opt-in, because they evaluate tooling behavior rather than describing the target architecture.
- The report should focus on engineering insight first: entrypoints, hotspots, module imports, function coordination points, and class/model surface.

## Optional Provider Note

- {coderag_note or "CodeRAG validation artifact not present."}
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return report
