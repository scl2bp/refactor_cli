from pathlib import Path
from typing import Any

from refactor_cli.discovery import load_config, resolve_project_root
from refactor_cli.file_io import load_json


DEFAULT_CONFIG = Path(".refactor/config.json")


DEFAULT_TREE = Path(".refactor/tree.yaml")


DEFAULT_TREE_PATCH = Path(".refactor/patches/latest.tree.patch.yaml")


DEFAULT_TREE_EDIT = Path(".refactor/patches/latest.tree.edit.yaml")


DEFAULT_APPLIED_PATCHES_DIR = Path(".refactor/patches/applied")


DEFAULT_CANDIDATE_OUTPUT_DIR = Path(".refactor/analysis/candidates")


DEFAULT_CANDIDATE_REPORT = DEFAULT_CANDIDATE_OUTPUT_DIR / "report.md"


# --- compact tree serialization -----------------------------------------------
# Format: files is a dict {path: [nodes]}
# Each node is either a plain string  "Kind name"  (leaf)
# or a one-key dict  {"Kind name": [children]}  (with members).


def _load_optional_config(config_path: Path) -> dict[str, Any]:
    if config_path.exists():
        return load_config(config_path)
    return {}


def _candidate_analysis_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("candidate_analysis", {})
    return raw if isinstance(raw, dict) else {}


def _config_or_default(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str) and not value.strip():
        return fallback
    return value


def _resolve_path_setting(project_root: Path, value: str | None, default: Path) -> Path:
    raw = _config_or_default(value, str(default))
    path = Path(raw)
    if path.is_absolute():
        return path
    return (project_root / path).resolve()


def _resolve_optional_project_root(
    args_project_root: str | None, config_path: Path, config: dict[str, Any]
) -> Path:
    if args_project_root:
        return Path(args_project_root).resolve()
    if config:
        return resolve_project_root(config_path, config)
    return Path(".").resolve()


def _find_default_config_path(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        config_path = candidate / DEFAULT_CONFIG
        if config_path.exists():
            return config_path
    return DEFAULT_CONFIG.resolve()


def _semantic_terms_setting(value: str | list[str] | None) -> list[str]:
    if value is None:
        return ["dependency", "refactor", "module", "call graph"]
    if isinstance(value, list):
        return [str(term).strip() for term in value if str(term).strip()]
    return [term.strip() for term in value.split(",") if term.strip()]


def _exclude_substrings_setting(value: list[str] | None) -> list[str]:
    if value is None:
        return [".eval."]
    return [str(token).strip() for token in value if str(token).strip()]


def _semantic_query_profiles_setting(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        query = str(item.get("query", "")).strip()
        terms = item.get("semantic_terms")
        if not name:
            continue
        if not query and not (isinstance(terms, list) and terms):
            continue
        row: dict[str, Any] = {
            "name": name,
            "query": query,
            "why": str(item.get("why", "")).strip(),
        }
        scope_path = str(item.get("scope_path", "")).strip()
        if scope_path:
            row["scope_path"] = scope_path
        if isinstance(terms, list):
            row["semantic_terms"] = [
                str(token).strip() for token in terms if str(token).strip()
            ]
        out.append(row)
    return out


def _load_summary_if_present(input_dir: Path) -> dict[str, Any]:
    summary_path = input_dir / "summary.json"
    if summary_path.exists():
        return load_json(summary_path)
    return {}
