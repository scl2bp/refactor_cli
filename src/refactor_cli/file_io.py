import datetime
import json
from pathlib import Path

import yaml


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data or {}


def write_yaml(path: Path, payload: dict) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def yaml_text(payload: dict) -> str:
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)


def archive_patch(patch_path: Path, applied_dir: Path) -> Path:
    """Move a patch file into the applied archive folder with a timestamp prefix."""

    applied_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = applied_dir / f"{timestamp}_{patch_path.name}"
    patch_path.rename(dest)
    return dest
