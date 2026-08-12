import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


def _python_module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def resolve_emend_runner() -> list[str] | None:
    """Resolve how to invoke emend in the current environment.

    Preference order:
    1) `uvx emend` (tool-managed ephemeral execution)
    2) `emend` CLI (typically from `pip install emend`)
    3) `python -m emend` (module entrypoint)
    """
    if shutil.which("uvx") is not None:
        return ["uvx", "emend"]
    if shutil.which("emend") is not None:
        return ["emend"]
    if _python_module_available("emend"):
        return [sys.executable, "-m", "emend"]
    return None


def ensure_runtime_dependencies(*, require_emend: bool) -> None:
    """Fail fast when external runtime tools are missing.

    The CLI invokes several tools via subprocess (python -m ruff/autoimport and uvx emend).
    This preflight keeps failures deterministic and actionable.
    """
    missing: list[str] = []

    if not _python_module_available("ruff"):
        missing.append("missing python module: ruff (pip install ruff)")

    if not _python_module_available("autoimport"):
        missing.append("missing python module: autoimport (pip install autoimport)")

    if require_emend and resolve_emend_runner() is None:
        missing.append(
            "missing emend runner: install one of: uv (for uvx), emend CLI, or python module emend"
        )

    if missing:
        details = "\n  - " + "\n  - ".join(missing)
        raise RuntimeError(
            "Runtime dependency check failed. Install required tools before running:\n"
            f"{details}"
        )


def run_formatter_on_file(path: Path) -> None:
    """Format a Python file with ruff; fail fast if formatting fails."""
    subprocess.run([sys.executable, "-m", "ruff", "format", str(path)], check=True)


def run_compile_check_on_file(path: Path) -> None:
    """Compile-check a Python file to catch syntax issues early."""
    subprocess.run([sys.executable, "-m", "py_compile", str(path)], check=True)


def run_autoimport_on_file(path: Path) -> None:
    """Automatically add missing imports to a Python file using autoimport."""
    result = subprocess.run(
        [sys.executable, "-m", "autoimport", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # autoimport failing is non-fatal: print a warning and continue
        print(
            f"  safeguard autoimport warning: {result.stderr.strip() or result.stdout.strip()}"
        )


def run_lint_check_on_file(path: Path) -> list[str]:
    """Lint-check a Python file with ruff; return violations (non-fatal).

    Selected rules:
      F821 - undefined name (catches missing imports such as @dataclass, Any, etc.)
      F401 - imported but unused (dead import after a move)
      E902 - I/O or tokenize error (unreadable file)

    Returns list of violation lines; does not raise.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "F821,F401,E902",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return []
    return result.stdout.strip().splitlines() if result.stdout.strip() else []


def _run_ruff_fix_imports(file_path: Path) -> None:
    """Run ruff --fix to merge fragmented imports and remove unused ones."""
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "I001,F401",
            "--fix",
            str(file_path),
        ],
        capture_output=True,
    )
