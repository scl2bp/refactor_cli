from __future__ import annotations

import argparse
import ast
import json
import os
from collections import deque
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class GraphData:
    modules: set[str]
    edges: dict[str, set[str]]
    module_files: dict[str, Path]
    edge_locations: dict[tuple[str, str], tuple[Path, int]]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze internal Python module dependencies for a package.",
    )
    parser.add_argument("--package", default="jlesson", help="Root package name")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root directory",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "ast", "grimp"],
        default="auto",
        help="Graph backend to use",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="How many top modules to show in fan-in/fan-out tables",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=10,
        help="Maximum number of cycles to print",
    )
    parser.add_argument(
        "--mermaid-out",
        type=Path,
        help="Write a package-group Mermaid graph to this file",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        help="Write a Markdown report with an embedded Mermaid diagram",
    )
    parser.add_argument(
        "--details-markdown-out",
        type=Path,
        help="Write a detailed Markdown report with module-level cycles and dependency paths",
    )
    parser.add_argument(
        "--focus-group",
        action="append",
        default=[],
        help="Focus a boundary pair in the details report using 'group_a:group_b'. Can be passed multiple times.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Write the raw module graph summary to this file as JSON",
    )
    return parser


def iter_python_files(package_dir: Path) -> Iterable[Path]:
    for path in package_dir.rglob("*.py"):
        if "__pycache__" not in path.parts:
            yield path


def module_name_for_file(root: Path, file_path: Path) -> str:
    relative = file_path.relative_to(root)
    if file_path.name == "__init__.py":
        return ".".join(relative.with_suffix("").parts[:-1])
    return ".".join(relative.with_suffix("").parts)


def resolve_relative_module(current_module: str, level: int, module: str | None) -> str:
    package_parts = current_module.split(".")[:-1]
    if level > len(package_parts) + 1:
        return module or ""
    anchor = package_parts[: len(package_parts) - level + 1]
    if module:
        return ".".join([*anchor, module])
    return ".".join(anchor)


def nearest_known_module(name: str, known_modules: set[str]) -> str | None:
    current = name
    while current:
        if current in known_modules:
            return current
        if "." not in current:
            break
        current = current.rsplit(".", 1)[0]
    return None


def collect_graph_metadata(
    root: Path,
    package: str,
    modules: set[str],
    edges: dict[str, set[str]],
) -> tuple[dict[str, Path], dict[tuple[str, str], tuple[Path, int]]]:
    package_dir = root / package.replace(".", "/")
    module_files: dict[str, Path] = {}
    edge_locations: dict[tuple[str, str], tuple[Path, int]] = {}

    for file_path in iter_python_files(package_dir):
        module_name = module_name_for_file(root, file_path)
        if module_name not in modules:
            continue

        module_files[module_name] = file_path
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))

        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not alias.name.startswith(f"{package}.") and alias.name != package:
                        continue
                    target = nearest_known_module(alias.name, modules)
                    if target and target in edges.get(module_name, set()) and target != module_name:
                        targets.append(target)

            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base_module = resolve_relative_module(module_name, node.level, node.module)
                else:
                    base_module = node.module or ""

                if not base_module.startswith(package):
                    continue

                for alias in node.names:
                    candidate = f"{base_module}.{alias.name}" if base_module else alias.name
                    target = nearest_known_module(candidate, modules)
                    if target is None:
                        target = nearest_known_module(base_module, modules)
                    if target and target in edges.get(module_name, set()) and target != module_name:
                        targets.append(target)

            for target in targets:
                edge_locations.setdefault((module_name, target), (file_path, node.lineno))

    return module_files, edge_locations


def graph_from_ast(root: Path, package: str) -> GraphData:
    package_dir = root / package.replace(".", "/")
    modules = {module_name_for_file(root, path) for path in iter_python_files(package_dir)}
    edges: dict[str, set[str]] = {module: set() for module in modules}

    for file_path in iter_python_files(package_dir):
        module_name = module_name_for_file(root, file_path)
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not alias.name.startswith(f"{package}.") and alias.name != package:
                        continue
                    target = nearest_known_module(alias.name, modules)
                    if target and target != module_name:
                        edges[module_name].add(target)

            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base_module = resolve_relative_module(module_name, node.level, node.module)
                else:
                    base_module = node.module or ""

                if not base_module.startswith(package):
                    continue

                for alias in node.names:
                    candidate = f"{base_module}.{alias.name}" if base_module else alias.name
                    target = nearest_known_module(candidate, modules)
                    if target is None:
                        target = nearest_known_module(base_module, modules)
                    if target and target != module_name:
                        edges[module_name].add(target)

    module_files, edge_locations = collect_graph_metadata(root, package, modules, edges)
    return GraphData(
        modules=modules,
        edges=edges,
        module_files=module_files,
        edge_locations=edge_locations,
    )


def graph_from_grimp(root: Path, package: str) -> GraphData:
    import grimp

    graph = grimp.build_graph(package, include_external_packages=False, cache_dir=None)
    modules = set(graph.modules)
    edges: dict[str, set[str]] = {module: set() for module in modules}
    for importer in modules:
        for imported in graph.find_modules_directly_imported_by(importer):
            if imported in modules and imported != importer:
                edges[importer].add(imported)
    module_files, edge_locations = collect_graph_metadata(root, package, modules, edges)
    return GraphData(
        modules=modules,
        edges=edges,
        module_files=module_files,
        edge_locations=edge_locations,
    )


def build_graph(root: Path, package: str, backend: str) -> tuple[GraphData, str]:
    if backend in {"auto", "grimp"}:
        try:
            return graph_from_grimp(root, package), "grimp"
        except ModuleNotFoundError:
            if backend == "grimp":
                raise
    return graph_from_ast(root, package), "ast"


def invert_edges(edges: dict[str, set[str]]) -> dict[str, set[str]]:
    inbound: dict[str, set[str]] = {module: set() for module in edges}
    for source, targets in edges.items():
        for target in targets:
            inbound[target].add(source)
    return inbound


def strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in graph[node]:
            if neighbor not in indices:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])

        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            visit(node)

    return [component for component in components if len(component) > 1]


def shortest_path(
    edges: dict[str, set[str]],
    source: str,
    target: str,
    *,
    allowed: set[str] | None = None,
) -> list[str] | None:
    if source == target:
        return [source]

    queue: deque[tuple[str, list[str]]] = deque([(source, [source])])
    seen = {source}

    while queue:
        node, path = queue.popleft()
        for neighbor in sorted(edges[node]):
            if allowed is not None and neighbor not in allowed:
                continue
            if neighbor in seen:
                continue
            new_path = [*path, neighbor]
            if neighbor == target:
                return new_path
            seen.add(neighbor)
            queue.append((neighbor, new_path))

    return None


def shortest_group_path(
    edges: dict[str, set[str]],
    modules: set[str],
    package: str,
    source_group: str,
    target_group: str,
) -> list[str] | None:
    best: list[str] | None = None
    sources = sorted(module for module in modules if module_group(module, package) == source_group)
    targets = sorted(module for module in modules if module_group(module, package) == target_group)

    for source in sources:
        for target in targets:
            path = shortest_path(edges, source, target)
            if path is None:
                continue
            if best is None or len(path) < len(best) or path < best:
                best = path
    return best


def direct_group_edges(
    edges: dict[str, set[str]],
    modules: set[str],
    package: str,
    source_group: str,
    target_group: str,
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for source in sorted(modules):
        if module_group(source, package) != source_group:
            continue
        for target in sorted(edges[source]):
            if target not in modules:
                continue
            if module_group(target, package) == target_group:
                pairs.append((source, target))
    return pairs


def cycle_nodes_for_groups(
    cycles: list[list[str]],
    package: str,
    left_group: str,
    right_group: str,
) -> set[str]:
    nodes: set[str] = set()
    for component in cycles:
        groups = {module_group(module, package) for module in component}
        if left_group in groups and right_group in groups:
            nodes.update(component)
    return nodes


def cycle_group_path(
    edges: dict[str, set[str]],
    package: str,
    source_group: str,
    target_group: str,
    allowed_nodes: set[str],
) -> list[str] | None:
    best: list[str] | None = None
    sources = sorted(
        module for module in allowed_nodes if module_group(module, package) == source_group
    )
    targets = sorted(
        module for module in allowed_nodes if module_group(module, package) == target_group
    )

    for source in sources:
        for target in targets:
            path = shortest_path(edges, source, target, allowed=allowed_nodes)
            if path is None:
                continue
            if best is None or len(path) < len(best) or path < best:
                best = path
    return best


def representative_cycle(edges: dict[str, set[str]], component: list[str]) -> list[str]:
    allowed = set(component)
    best_cycle: list[str] | None = None

    for source in component:
        for neighbor in sorted(edges[source]):
            if neighbor not in allowed:
                continue
            return_path = shortest_path(edges, neighbor, source, allowed=allowed)
            if return_path is None:
                continue
            cycle_path = [source, *return_path]
            if best_cycle is None or len(cycle_path) < len(best_cycle):
                best_cycle = cycle_path

    return best_cycle or component


def module_group(module: str, package: str) -> str:
    parts = module.split(".")
    if module == package or len(parts) == 1:
        return "(root)"
    return parts[1]


def default_focus_groups(package: str) -> list[tuple[str, str]]:
    if package == "jlesson":
        return [
            ("lesson_pipeline", "video"),
            ("lesson_pipeline", "asset_compiler"),
        ]
    return []


def parse_focus_groups(values: list[str], package: str) -> list[tuple[str, str]]:
    if not values:
        return default_focus_groups(package)

    parsed: list[tuple[str, str]] = []
    for value in values:
        if ":" not in value:
            raise ValueError(
                f"Invalid --focus-group value '{value}'. Expected format 'group_a:group_b'."
            )
        left, right = value.split(":", 1)
        left = left.strip()
        right = right.strip()
        if not left or not right:
            raise ValueError(
                f"Invalid --focus-group value '{value}'. Expected format 'group_a:group_b'."
            )
        parsed.append((left, right))
    return parsed


def group_edges(modules: Iterable[str], edges: dict[str, set[str]], package: str) -> dict[str, Counter[str]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for source in modules:
        source_group = module_group(source, package)
        for target in edges[source]:
            target_group = module_group(target, package)
            if source_group != target_group:
                grouped[source_group][target_group] += 1
    return grouped


def render_mermaid(grouped_edges: dict[str, Counter[str]]) -> str:
    lines = ["flowchart LR"]
    for source in sorted(grouped_edges):
        for target, count in grouped_edges[source].most_common():
            lines.append(f"    {sanitize_id(source)} -->|{count}| {sanitize_id(target)}")
    for label in sorted({*grouped_edges.keys(), *(t for counters in grouped_edges.values() for t in counters)}):
        lines.append(f"    {sanitize_id(label)}[{label}]")
    return "\n".join(lines) + "\n"


def markdown_link(report_path: Path, target_path: Path, label: str, line: int | None = None) -> str:
    relative = Path(os.path.relpath(target_path, report_path.parent)).as_posix()
    if line is not None:
        return f"[{label}]({relative}#L{line})"
    return f"[{label}]({relative})"


def module_text(module: str) -> str:
    return f"`{module}`"


def module_ellipsis_link(module: str, graph: GraphData, report_path: Path) -> str | None:
    file_path = graph.module_files.get(module)
    if file_path is None:
        return None
    return markdown_link(report_path, file_path, "...", line=1)


def edge_ellipsis_link(source: str, target: str, graph: GraphData, report_path: Path) -> str | None:
    location = graph.edge_locations.get((source, target))
    if location is None:
        return None
    file_path, line = location
    return markdown_link(report_path, file_path, "...", line=line)


def format_path_text(path: list[str]) -> str:
    return " -> ".join(module_text(module) for module in path)


def path_ellipsis_link(path: list[str], graph: GraphData, report_path: Path) -> str | None:
    if len(path) >= 2:
        link = edge_ellipsis_link(path[0], path[1], graph, report_path)
        if link is not None:
            return link
    if path:
        return module_ellipsis_link(path[0], graph, report_path)
    return None


def render_markdown_report(
    *,
    package: str,
    backend_used: str,
    graph: GraphData,
    grouped: dict[str, Counter[str]],
    cycles: list[list[str]],
    in_degree: Counter[str],
    out_degree: Counter[str],
    top: int,
    report_path: Path,
) -> str:
    lines = [
        f"# Internal Module Dependencies: {package}",
        "",
        f"- Backend: `{backend_used}`",
        f"- Modules: `{len(graph.modules)}`",
        f"- Internal edges: `{sum(len(targets) for targets in graph.edges.values())}`",
        f"- Cycles: `{len(cycles)}`",
        "",
        "## Diagram",
        "",
        "```mermaid",
        render_mermaid(grouped).rstrip(),
        "```",
        "",
        "## Highest Fan-Out",
        "",
    ]

    for module, count in out_degree.most_common(top):
        entry = f"- {module_text(module)}: `{count}`"
        source_link = module_ellipsis_link(module, graph, report_path)
        if source_link is not None:
            entry = f"{entry} {source_link}"
        lines.append(entry)

    lines.extend([
        "",
        "## Highest Fan-In",
        "",
    ])

    for module, count in in_degree.most_common(top):
        entry = f"- {module_text(module)}: `{count}`"
        source_link = module_ellipsis_link(module, graph, report_path)
        if source_link is not None:
            entry = f"{entry} {source_link}"
        lines.append(entry)

    lines.extend([
        "",
        "## Cross-Group Dependencies",
        "",
    ])

    if not grouped:
        lines.append("- None")
    else:
        for source in sorted(grouped):
            summary = ", ".join(
                f"`{target}` ({count})" for target, count in grouped[source].most_common()
            )
            lines.append(f"- `{source}` -> {summary}")

    lines.extend([
        "",
        "## Cycles",
        "",
    ])

    if not cycles:
        lines.append("- None")
    else:
        for component in cycles:
            entry = f"- {format_path_text(component)}"
            source_link = path_ellipsis_link(component, graph, report_path)
            if source_link is not None:
                entry = f"{entry} {source_link}"
            lines.append(entry)

    lines.append("")
    return "\n".join(lines)


def top_dependency_paths(
    edges: dict[str, set[str]],
    out_degree: Counter[str],
    in_degree: Counter[str],
    *,
    top_sources: int = 5,
    per_source: int = 3,
    min_hops: int = 2,
) -> dict[str, list[list[str]]]:
    results: dict[str, list[list[str]]] = {}

    for source, _ in out_degree.most_common(top_sources):
        candidates: list[tuple[int, int, str, list[str]]] = []
        for target in sorted(edges):
            if target == source:
                continue
            path = shortest_path(edges, source, target)
            if path is None:
                continue
            hops = len(path) - 1
            if hops < min_hops:
                continue
            candidates.append((hops, in_degree[target], target, path))

        if not candidates:
            continue

        candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
        results[source] = [path for _, _, _, path in candidates[:per_source]]

    return results


def render_detailed_markdown_report(
    *,
    package: str,
    backend_used: str,
    graph: GraphData,
    cycles: list[list[str]],
    in_degree: Counter[str],
    out_degree: Counter[str],
    top: int,
    focus_groups: list[tuple[str, str]],
    report_path: Path,
) -> str:
    cycle_paths = [representative_cycle(graph.edges, component) for component in cycles]
    dependency_paths = top_dependency_paths(
        graph.edges,
        out_degree,
        in_degree,
        top_sources=min(5, max(1, top // 2)),
        per_source=3,
        min_hops=2,
    )

    lines = [
        f"# Internal Module Dependency Details: {package}",
        "",
        f"- Backend: `{backend_used}`",
        f"- Modules: `{len(graph.modules)}`",
        f"- Internal edges: `{sum(len(targets) for targets in graph.edges.values())}`",
        f"- Cycle components: `{len(cycles)}`",
        "",
        "## Cycle Paths",
        "",
    ]

    if not cycle_paths:
        lines.append("- None")
    else:
        for path in cycle_paths:
            entry = f"- {format_path_text(path)}"
            source_link = path_ellipsis_link(path, graph, report_path)
            if source_link is not None:
                entry = f"{entry} {source_link}"
            lines.append(entry)

    lines.extend([
        "",
        "## Focused Boundaries",
        "",
    ])

    if not focus_groups:
        lines.append("- None")
    else:
        for left_group, right_group in focus_groups:
            lines.append(f"### `{left_group}` <-> `{right_group}`")
            lines.append("")

            cycle_nodes = cycle_nodes_for_groups(cycles, package, left_group, right_group)
            left_to_right_edges = direct_group_edges(
                graph.edges,
                graph.modules,
                package,
                left_group,
                right_group,
            )
            right_to_left_edges = direct_group_edges(
                graph.edges,
                graph.modules,
                package,
                right_group,
                left_group,
            )
            cycle_left_to_right_edges = direct_group_edges(
                graph.edges,
                cycle_nodes,
                package,
                left_group,
                right_group,
            ) if cycle_nodes else []
            cycle_right_to_left_edges = direct_group_edges(
                graph.edges,
                cycle_nodes,
                package,
                right_group,
                left_group,
            ) if cycle_nodes else []
            left_to_right_path = cycle_group_path(
                graph.edges,
                package,
                left_group,
                right_group,
                cycle_nodes,
            ) if cycle_nodes else None
            right_to_left_path = cycle_group_path(
                graph.edges,
                package,
                right_group,
                left_group,
                cycle_nodes,
            ) if cycle_nodes else None

            lines.append(f"- Direct imports `{left_group}` -> `{right_group}`: `{len(left_to_right_edges)}`")
            if left_to_right_edges:
                for source, target in left_to_right_edges[:8]:
                    import_link = edge_ellipsis_link(source, target, graph, report_path)
                    edge_summary = f"{module_text(source)} -> {module_text(target)}"
                    if import_link is not None:
                        edge_summary = f"{edge_summary} {import_link}"
                    lines.append(f"  - {edge_summary}")

            lines.append(f"- Direct imports `{right_group}` -> `{left_group}`: `{len(right_to_left_edges)}`")
            if right_to_left_edges:
                for source, target in right_to_left_edges[:8]:
                    import_link = edge_ellipsis_link(source, target, graph, report_path)
                    edge_summary = f"{module_text(source)} -> {module_text(target)}"
                    if import_link is not None:
                        edge_summary = f"{edge_summary} {import_link}"
                    lines.append(f"  - {edge_summary}")

            lines.append(f"- Cycle nodes spanning both groups: `{len(cycle_nodes)}`")
            if cycle_nodes:
                lines.append(
                    f"- Cycle-direct imports `{left_group}` -> `{right_group}`: `{len(cycle_left_to_right_edges)}`"
                )
                if cycle_left_to_right_edges:
                    for source, target in cycle_left_to_right_edges[:8]:
                        import_link = edge_ellipsis_link(source, target, graph, report_path)
                        edge_summary = f"{module_text(source)} -> {module_text(target)}"
                        if import_link is not None:
                            edge_summary = f"{edge_summary} {import_link}"
                        lines.append(f"  - {edge_summary}")
                lines.append(
                    f"- Cycle-direct imports `{right_group}` -> `{left_group}`: `{len(cycle_right_to_left_edges)}`"
                )
                if cycle_right_to_left_edges:
                    for source, target in cycle_right_to_left_edges[:8]:
                        import_link = edge_ellipsis_link(source, target, graph, report_path)
                        edge_summary = f"{module_text(source)} -> {module_text(target)}"
                        if import_link is not None:
                            edge_summary = f"{edge_summary} {import_link}"
                        lines.append(f"  - {edge_summary}")

            if left_to_right_path is not None:
                entry = f"- Cycle path `{left_group}` -> `{right_group}`: {format_path_text(left_to_right_path)}"
                source_link = path_ellipsis_link(left_to_right_path, graph, report_path)
                if source_link is not None:
                    entry = f"{entry} {source_link}"
                lines.append(entry)
            else:
                lines.append(f"- Cycle path `{left_group}` -> `{right_group}`: none")

            if right_to_left_path is not None:
                entry = f"- Cycle path `{right_group}` -> `{left_group}`: {format_path_text(right_to_left_path)}"
                source_link = path_ellipsis_link(right_to_left_path, graph, report_path)
                if source_link is not None:
                    entry = f"{entry} {source_link}"
                lines.append(entry)
            else:
                lines.append(f"- Cycle path `{right_group}` -> `{left_group}`: none")

            lines.append("")

    lines.extend([
        "",
        "## Top Transitive Dependency Paths",
        "",
    ])

    if not dependency_paths:
        lines.append("- None")
    else:
        for source, paths in dependency_paths.items():
            header = f"### {module_text(source)}"
            source_link = module_ellipsis_link(source, graph, report_path)
            if source_link is not None:
                header = f"{header} {source_link}"
            lines.append(header)
            lines.append("")
            for path in paths:
                entry = f"- {format_path_text(path)}"
                source_link = path_ellipsis_link(path, graph, report_path)
                if source_link is not None:
                    entry = f"{entry} {source_link}"
                lines.append(entry)
            lines.append("")

    lines.extend([
        "## Direct Imports For Highest Fan-Out Modules",
        "",
    ])

    for module, _ in out_degree.most_common(min(top, 10)):
        direct_imports = sorted(graph.edges[module])
        header = f"### {module_text(module)}"
        source_link = module_ellipsis_link(module, graph, report_path)
        if source_link is not None:
            header = f"{header} {source_link}"
        lines.append(header)
        lines.append("")
        if not direct_imports:
            lines.append("- None")
        else:
            for imported in direct_imports:
                import_link = edge_ellipsis_link(module, imported, graph, report_path)
                entry = module_text(imported)
                if import_link is not None:
                    entry = f"{entry} {import_link}"
                lines.append(f"- {entry}")
        lines.append("")

    return "\n".join(lines)


def sanitize_id(label: str) -> str:
    return label.replace("(", "").replace(")", "").replace("-", "_").replace(".", "_") or "root"


def print_counter(title: str, counter: Counter[str], limit: int) -> None:
    print(title)
    if not counter:
        print("  (none)")
        return
    for module, count in counter.most_common(limit):
        print(f"  {count:>3}  {module}")


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    if args.markdown_out is None:
        args.markdown_out = root / "docs" / "internal_module_dependencies.md"
    if args.details_markdown_out is None:
        args.details_markdown_out = root / "docs" / "internal_module_dependency_details.md"
    focus_groups = parse_focus_groups(args.focus_group, args.package)
    graph, backend_used = build_graph(root, args.package, args.backend)
    inbound = invert_edges(graph.edges)
    cycles = strongly_connected_components(graph.edges)

    out_degree = Counter({module: len(targets) for module, targets in graph.edges.items()})
    in_degree = Counter({module: len(sources) for module, sources in inbound.items()})
    grouped = group_edges(graph.modules, graph.edges, args.package)

    print(f"backend: {backend_used}")
    print(f"package: {args.package}")
    print(f"modules: {len(graph.modules)}")
    print(f"internal edges: {sum(len(targets) for targets in graph.edges.values())}")
    print(f"cycles: {len(cycles)}")
    print()

    print_counter("highest fan-out:", out_degree, args.top)
    print()
    print_counter("highest fan-in:", in_degree, args.top)
    print()

    print("cross-group dependencies:")
    if not grouped:
        print("  (none)")
    else:
        for source in sorted(grouped):
            summary = ", ".join(
                f"{target} ({count})" for target, count in grouped[source].most_common()
            )
            print(f"  {source} -> {summary}")

    if cycles:
        print()
        print("cycles:")
        for component in cycles[: args.max_cycles]:
            print(f"  {' -> '.join(component)}")
        if len(cycles) > args.max_cycles:
            print(f"  ... {len(cycles) - args.max_cycles} more")

    if args.mermaid_out:
        args.mermaid_out.write_text(render_mermaid(grouped), encoding="utf-8")
        print()
        print(f"wrote mermaid: {args.mermaid_out}")

    markdown = render_markdown_report(
        package=args.package,
        backend_used=backend_used,
        graph=graph,
        grouped=grouped,
        cycles=cycles,
        in_degree=in_degree,
        out_degree=out_degree,
        top=args.top,
        report_path=args.markdown_out,
    )
    args.markdown_out.write_text(markdown, encoding="utf-8")
    print(f"wrote markdown: {args.markdown_out}")

    details_markdown = render_detailed_markdown_report(
        package=args.package,
        backend_used=backend_used,
        graph=graph,
        cycles=cycles,
        in_degree=in_degree,
        out_degree=out_degree,
        top=args.top,
        focus_groups=focus_groups,
        report_path=args.details_markdown_out,
    )
    args.details_markdown_out.write_text(details_markdown, encoding="utf-8")
    print(f"wrote details markdown: {args.details_markdown_out}")

    if args.json_out:
        payload = {
            "backend": backend_used,
            "package": args.package,
            "modules": sorted(graph.modules),
            "module_files": {
                module: path.relative_to(root).as_posix()
                for module, path in sorted(graph.module_files.items())
            },
            "edges": {module: sorted(targets) for module, targets in sorted(graph.edges.items())},
            "edge_locations": {
                f"{source} -> {target}": {
                    "path": path.relative_to(root).as_posix(),
                    "line": line,
                }
                for (source, target), (path, line) in sorted(graph.edge_locations.items())
            },
            "cycles": cycles,
            "fan_in": in_degree.most_common(),
            "fan_out": out_degree.most_common(),
            "cross_group": {
                source: grouped[source].most_common() for source in sorted(grouped)
            },
        }
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote json: {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())