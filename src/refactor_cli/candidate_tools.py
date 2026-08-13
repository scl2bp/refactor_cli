from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def resolve_cbm_binary(explicit_path: str | None = None) -> Path:
    if explicit_path:
        candidate = Path(explicit_path)
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"CBM binary not found: {candidate}")

    local = Path(".eval/tools/cbm/codebase-memory-mcp")
    if local.exists():
        return local

    discovered = shutil.which("codebase-memory-mcp")
    if discovered:
        return Path(discovered)

    raise FileNotFoundError(
        "Could not locate codebase-memory-mcp binary. Set --cbm-binary or install candidate tools."
    )


def _flag_name(key: str) -> str:
    return f"--{key.replace('_', '-')}"


def _flag_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def _extract_json_line(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{") or not stripped.endswith("}"):
            continue
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            continue
    return {}


def run_cbm_tool(
    cbm_binary: Path,
    tool_name: str,
    flags: dict[str, Any],
    cwd: Path,
) -> dict[str, Any]:
    cmd = [str(cbm_binary), "cli", "--json", tool_name]
    for key, value in flags.items():
        if value is None:
            continue
        cmd.extend([_flag_name(key), _flag_value(value)])

    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    payload = _extract_json_line(result.stdout)

    return {
        "ok": result.returncode == 0 and not payload.get("isError", False),
        "returncode": result.returncode,
        "tool": tool_name,
        "flags": flags,
        "payload": payload,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "command": cmd,
    }
