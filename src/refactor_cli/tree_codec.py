from pathlib import Path

import yaml

from refactor_cli import _compact_to_node, _node_to_compact
from refactor_cli.file_io import ensure_parent, load_yaml


def _node_to_compact(node: dict) -> "str | dict":
    label = f"{node['kind']} {node['name']}"
    children = node.get("children", [])
    if not children:
        return label
    return {label: [_node_to_compact(c) for c in children]}


def _compact_to_node(item: "str | dict") -> dict:
    if isinstance(item, str):
        kind, _, name = item.partition(" ")
        return {"kind": kind, "name": name, "children": []}
    label = next(iter(item))
    kind, _, name = label.partition(" ")
    return {
        "kind": kind,
        "name": name,
        "children": [_compact_to_node(c) for c in item[label]],
    }


def write_tree_yaml(path: Path, payload: dict) -> None:
    compact = {
        "version": payload["version"],
        "root": payload["root"],
        "files": {
            entry["path"]: [_node_to_compact(n) for n in entry.get("nodes", [])]
            for entry in payload["files"]
        },
    }
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(compact, fh, sort_keys=False, allow_unicode=False)


def load_tree_yaml(path: Path) -> dict:
    raw = load_yaml(path)
    return {
        "version": raw.get("version", 1),
        "root": raw.get("root", ""),
        "files": [
            {"path": file_path, "nodes": [_compact_to_node(n) for n in (nodes or [])]}
            for file_path, nodes in raw.get("files", {}).items()
        ],
    }
