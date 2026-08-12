from pathlib import Path

import libcst as cst

from refactor_cli.file_io import load_json


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing config: {path}. Run `python tools/structural_refactor.py init` first."
        )
    return load_json(path)


def resolve_project_root(config_path: Path, config: dict) -> Path:
    root = config.get("project_root", "..")
    return (config_path.parent / root).resolve()


def discover_python_files(root: Path, config: dict) -> list[Path]:
    file_cfg = config.get("python_files", {})
    include = file_cfg.get("include", ["**/*.py"])
    exclude = file_cfg.get("exclude", [])

    matches: set[Path] = set()
    for pattern in include:
        matches.update(path for path in root.glob(pattern) if path.is_file())

    filtered: list[Path] = []
    for path in sorted(matches):
        rel = path.relative_to(root).as_posix()
        excluded = any(
            path.match(pattern) or rel.startswith(pattern.rstrip("/**"))
            for pattern in exclude
        )
        if not excluded:
            filtered.append(path)
    return filtered


def load_module(path: Path) -> cst.Module:
    return cst.parse_module(path.read_text(encoding="utf-8"))


def statement_name(statement: cst.BaseStatement) -> str | None:
    if isinstance(statement, cst.FunctionDef):
        return statement.name.value
    if isinstance(statement, cst.ClassDef):
        return statement.name.value
    if isinstance(statement, cst.SimpleStatementLine):
        for expr in statement.body:
            if isinstance(expr, cst.Assign) and len(expr.targets) == 1:
                target = expr.targets[0].target
                if isinstance(target, cst.Name):
                    return target.value
    return None


def is_import_statement(statement: cst.BaseStatement) -> bool:
    return isinstance(statement, (cst.Import, cst.ImportFrom))


def render_statements(
    module: cst.Module, statements: list[cst.BaseStatement], separator: str = "\n\n"
) -> str:
    if not statements:
        return ""
    rendered = [module.code_for_node(statement).rstrip() for statement in statements]
    return separator.join(rendered).rstrip() + "\n"


def build_tree(module: cst.Module) -> list[dict]:
    tree: list[dict] = []
    for statement in module.body:
        name = statement_name(statement)
        if name is None:
            continue

        node = {
            "kind": type(statement).__name__,
            "name": name,
            "children": [],
        }
        if isinstance(statement, cst.ClassDef):
            for member in statement.body.body:
                member_name = statement_name(member)
                if member_name is not None:
                    node["children"].append(
                        {
                            "kind": type(member).__name__,
                            "name": member_name,
                        }
                    )
        tree.append(node)
    return tree


def print_tree(nodes: list[dict], indent_level: int = 0) -> None:
    prefix = "  " * indent_level
    for node in nodes:
        print(f"{prefix}- {node['kind']}: {node['name']}")
        children = node.get("children", [])
        if children:
            print_tree(children, indent_level + 1)


def generate_tree_payload(config_path: Path) -> dict:
    config = load_config(config_path)
    root = resolve_project_root(config_path, config)
    files = discover_python_files(root, config)

    payload = {
        "version": 1,
        "root": root.as_posix(),
        "files": [],
    }
    for path in files:
        module = load_module(path)
        payload["files"].append(
            {
                "path": path.relative_to(root).as_posix(),
                "nodes": build_tree(module),
            }
        )
    return payload
