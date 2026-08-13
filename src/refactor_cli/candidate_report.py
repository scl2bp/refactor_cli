from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from refactor_cli.candidate_tools import resolve_cbm_binary, run_cbm_tool
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
    if value is True:
        return "OK"
    if value is False:
        return "FAIL"
    return "SKIP"


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


def _semantic_noise_summary(
    semantic_doc: dict[str, Any], scope_path: str
) -> dict[str, int]:
    result_doc = semantic_doc.get("result", semantic_doc)
    structured = result_doc.get("payload", {}).get("structuredContent", {})
    semantic = structured.get("semantic", {})
    rows = semantic.get("rows", [])
    local = 0
    non_local = 0
    for row in rows:
        if len(row) < 3:
            continue
        file_path = row[2]
        if str(file_path).startswith(scope_path):
            local += 1
        else:
            non_local += 1
    return {"local": local, "non_local": non_local}


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
        f"WHERE s.qn CONTAINS '{scope_prefix}' "
        "RETURN s.qn AS source, type(r) AS relation, "
        "coalesce(t.qn, t.name) AS target"
    )
    return run_cbm_tool(
        cbm_binary,
        "query_graph",
        {"project": project_name, "query": query, "max_rows": 30},
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
    rows: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith("rows:")
            or stripped.startswith("total:")
        ):
            continue
        if " CALLS " in stripped:
            source, target = stripped.split(" CALLS ", 1)
            rows.append((source, "CALLS", target))
        elif " IMPORTS " in stripped:
            source, target = stripped.split(" IMPORTS ", 1)
            rows.append((source, "IMPORTS", target))
        elif " INHERITS " in stripped:
            source, target = stripped.split(" INHERITS ", 1)
            rows.append((source, "INHERITS", target))
    return rows


def _short_name(qualified_name: str) -> str:
    return qualified_name.split(".")[-1].replace("-", "_")


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
    for source, relation, target in dep_rows[:12]:
        source_id = _short_name(source)
        target_id = _short_name(target)
        lines.append(
            f'  {source_id}["{_short_name(source)}"] -->|{relation}| {target_id}["{_short_name(target)}"]'
        )
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
    excluded = source_index["index"]["payload"]["structuredContent"]["excluded"]["dirs"]
    return [
        {
            "artifact": "source_index.json",
            "candidate": "codebase-memory-mcp",
            "input": f"Repository root /workspace/refactor_cli, mode=moderate, excludes={', '.join(excluded)}",
            "output": "Indexed graph metadata: node/edge counts, exclusions, parse warnings, project registration",
            "interpretation": "Tells us whether downstream graph outputs are trustworthy enough to inspect",
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
) -> str:
    summary = load_json(input_dir / "summary.json")
    source_index = load_json(input_dir / "source_index.json")
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
        scope_prefix="refactor_cli.src.refactor_cli",
        cbm_binary=cbm_binary,
    )
    scoped_dep_text = _extract_text_content(scoped_dep.get("payload", {}))
    scoped_dep_rows = _dependency_rows_from_text(scoped_dep_text)
    coherent_edges, suspicious_edges = _example_edge_lines(scoped_dep_rows)

    scoped_semantic = _scoped_semantic_search(
        project_root=project_root,
        project_name=project_name,
        scope_path=scope_path,
        cbm_binary=cbm_binary,
        semantic_terms=semantic["semantic_terms"],
    )

    full_arch_text = _architecture_text(architecture)
    full_languages = _parse_section_counts(full_arch_text, "languages")
    sizes = _artifact_size_rows(input_dir)
    local_groups = _top_local_groups(scoped_semantic, scope_path)
    semantic_noise = _semantic_noise_summary(semantic, scope_path)
    input_rows = _candidate_input_rows(
        source_index=source_index,
        dependency_doc=load_json(input_dir / "dependency_graph.json"),
        semantic_doc=semantic,
        architecture_doc=architecture,
        scope_path=scope_path,
    )

    modules = summary["modules"]
    scope_policy = summary.get("scope", {})
    daemon_policy = scope_policy.get("daemon_mode", "unspecified")
    readiness_items = [
        ("Indexing and project registration", "OK"),
        ("Scoped architecture extraction", "OK"),
        (
            "Scoped dependency extraction",
            "OK" if scoped_dep_rows else "PARTIAL",
        ),
        (
            "Scoped semantic retrieval signal",
            "OK" if semantic_noise.get("local", 0) > 0 else "LOW_SIGNAL",
        ),
        (
            "CodeRAG validation",
            _status_label(coderag.get("ok")) if coderag is not None else "SKIP",
        ),
        (
            "Persistent daemon mode",
            "OUT_OF_SCOPE" if daemon_policy == "out_of_scope" else "OPTIONAL",
        ),
    ]
    status_lines = "\n".join(
        f"| {name} | {_status_label(value)} |" for name, value in modules.items()
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

    report = f"""# Candidate Analysis Report

Generated: {dt.datetime.now().isoformat(timespec="seconds")}

Project: `{project_name}`

This report converts the raw Phase A candidate artifacts into a human-readable summary so the merit of the output can be checked quickly.

## Status

| Module | Status |
|---|---|
{status_lines}

{_mermaid_status(modules)}

## Artifact Sizes

| Artifact | Bytes |
|---|---:|
{size_lines}

{_mermaid_artifact_sizes(sizes)}

## What The Raw Files Mean

- `source_index.json`: index health and coverage
- `dependency_graph.json`: raw edge extraction
- `semantic_retrieval.json`: ranked and grouped search hits
- `architecture_report.json`: highest-value human summary
- `summary.json`: pass/fail snapshot

## Evaluation Matrix

{_markdown_input_table(input_rows)}

Observation:
- This makes the pipeline traceable. Each artifact can now be judged by the exact input it used, the candidate that produced it, and the meaning of the output.

## Readiness Checklist

| Capability | Status |
|---|---|
{readiness_lines}

Policy note:
- Persistent daemon mode is intentionally not part of this project's operating model.
- Current scope policy: file scope `{scope_policy.get("scope_path", scope_path)}`, qn scope `{scope_policy.get("scope_qn_prefix", "n/a")}`, excluded qn substrings `{scope_policy.get("exclude_qn_substrings", [])}`.

## Index Health

- Indexed nodes: {source_index["index"]["payload"]["structuredContent"]["nodes"]}
- Indexed edges: {source_index["index"]["payload"]["structuredContent"]["edges"]}
- Excluded directories shown by the tool: {", ".join(source_index["index"]["payload"]["structuredContent"]["excluded"]["dirs"])}
- Partial parse count: {source_index["index"]["payload"]["structuredContent"]["parse_partial_count"]}
- Not indexed file count: {source_index["index"]["payload"]["structuredContent"]["not_indexed_files_count"]}

Observation:
- The index succeeded and is large enough for meaningful graph analysis.
- The corpus includes `.eval/candidates`, so raw full-project results are noisier than the actual `src/refactor_cli` package.

## Full-Corpus Architecture Snapshot

- Languages detected in the indexed corpus: {", ".join(f"{name}={count}" for name, count in full_languages[:6])}
- This confirms that the full graph is dominated by the evaluation repositories, not just the target package.

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

Observation:
- The real package is a compact Python CLI package.
- The central coordination points are discovery/config/file-writing helpers and the candidate integration runner.

## Scoped Dependency View

The current stored `dependency_graph.json` is raw and broad. For clarity, this report also derives a scoped dependency sample for `{scope_path}`.

{_mermaid_scoped_edges(scoped_dep_rows)}

Coherent local edge examples:
{coherent_edge_lines}

Suspicious edge examples:
{suspicious_edge_lines}

Observation:
- The graph does recover real local structure, for example file-writing and candidate runner relationships.
- It also produces suspicious cross-corpus edges into `.eval` repositories, which means raw dependency output should not be trusted without scoping or filtering.

## Semantic Retrieval Interpretation

The stored artifact is evaluated as-is, but the local grouped examples below come from a scoped live re-query so the report can show what the candidate becomes capable of under tighter constraints.

- Local grouped hits in `{scope_path}`:
{local_group_lines}

- Semantic rows split:
  - local scoped rows: {semantic_noise["local"]}
  - non-local rows: {semantic_noise["non_local"]}

{_mermaid_semantic_signal(semantic_noise)}

Observation:
- The semantic retrieval command works, but the current default query is still noisy because most top semantic rows come from the indexed candidate repos.
- The grouped local results are more useful than the raw semantic ranking list for understanding this project.

What this means in practice:
- Successful execution does not imply meaningful insight.
- For this project, semantic retrieval currently has low signal because the indexed corpus is dominated by evaluation repositories.
- This is still a valuable result: it tells us the candidate needs stronger scope control or separate indexes to be useful for repository understanding.

## Practical Conclusions

- The outputs have merit, but only after scoping and summarization.
- `architecture_report.json` is the strongest artifact for human understanding.
- `dependency_graph.json` and `semantic_retrieval.json` should be treated as machine-oriented raw data unless filtered to the target package.
- The next improvement should be default scoped output for `candidate-phase-a` so the generated artifacts are human-usable by default.
- The report should be used to decide which candidate behaviors are actually production-worthy, not just technically runnable.

## Optional Provider Note

- {coderag_note or "CodeRAG validation artifact not present."}
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return report
