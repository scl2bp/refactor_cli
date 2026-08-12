from pathlib import Path

from refactor_cli.runtime_tools import (
    run_autoimport_on_file,
    run_compile_check_on_file,
    run_formatter_on_file,
    run_lint_check_on_file,
)


def post_apply_safeguards(
    root: Path, affected_rel_paths: list[str]
) -> dict[str, list[str]]:
    """Run formatter, autoimport, compile, and lint on all affected files.

    Returns a dict mapping rel_path -> list of lint violations (empty if none).
    Does not raise; collects issues for reporting at the end.
    """
    unique_paths = sorted(set(affected_rel_paths))
    all_violations: dict[str, list[str]] = {}

    for rel_path in unique_paths:
        if not rel_path.endswith(".py"):
            continue
        file_path = root / rel_path
        if not file_path.exists():
            print(f"  safeguard skip (missing): {rel_path}")
            continue
        print(f"  safeguard format:    {rel_path}")
        run_formatter_on_file(file_path)
        print(f"  safeguard autoimport:{rel_path}")
        run_autoimport_on_file(file_path)
        print(f"  safeguard compile:   {rel_path}")
        run_compile_check_on_file(file_path)
        print(f"  safeguard lint:      {rel_path}")
        violations = run_lint_check_on_file(file_path)
        if violations:
            all_violations[rel_path] = violations
            for violation_line in violations:
                print(f"    {violation_line}")

    return all_violations
