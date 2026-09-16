"""
Structural duplication detector for Python source files.

Two detection modes:
  1. Token-level similarity  (default, within a single --file)
     Compares normalised token streams; good for near-identical logic with
     different variable names.

  2. AST-hash exact clones   (--multi / --compare-baseline)
     Hashes normalised AST dumps across multiple files; same algorithm used
     by quality_gate_report.py so the numbers are directly comparable.

Usage:
    # Single-file similarity scan (original behaviour)
    python tools/find_duplicates.py [--threshold 0.75] [--prefix _rule_]

    # Multi-file exact-clone scan
    python tools/find_duplicates.py --multi [src/felvi_games tests]

    # Show only pairs that are NEW compared to the saved quality-gate baseline
    python tools/find_duplicates.py --multi --compare-baseline

    # Full delta report: which high-param fns and unused fns are new too
    python tools/find_duplicates.py --compare-baseline --full-delta
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import sys
import textwrap
import tokenize
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

TARGET = Path("src/felvi_games/achievements.py")
DEFAULT_SCAN_PATHS = ["src/felvi_games", "tests"]
BASELINE_PATH = Path("reports/quality/complexity_baseline.json")
CURRENT_PATH = Path("reports/quality/complexity_current.json")
SKIP_DIRS = frozenset(
    {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    """Remove leading docstring from a function body."""
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        return body[1:]
    return body


def _body_source(func: ast.FunctionDef, source_lines: list[str]) -> str:
    """Return the raw source of the function body (excluding signature + docstring)."""
    body = _strip_docstring(func.body)
    if not body:
        return ""
    start = body[0].lineno - 1
    end = func.end_lineno  # inclusive
    raw = "\n".join(source_lines[start:end])
    return textwrap.dedent(raw)


# ---------------------------------------------------------------------------
# Token normalization
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"\b[a-zA-Z_]\w*\b")


def _normalize_tokens(code: str) -> str:
    """
    Produce a normalized token string for comparison:
    - collapse all whitespace to single space
    - remove comments
    - keep structural tokens (keywords, operators, punctuation)
    - replace string literals with STR, number literals with NUM
    """
    try:
        tokens = tokenize.generate_tokens(io.StringIO(code).readline)
        parts: list[str] = []
        for tok_type, tok_val, _, _, _ in tokens:
            if tok_type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                            tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING):
                continue
            if tok_type == tokenize.STRING:
                parts.append("STR")
            elif tok_type == tokenize.NUMBER:
                parts.append("NUM")
            elif tok_type == tokenize.NAME:
                parts.append(tok_val)
            else:
                parts.append(tok_val)
        return " ".join(parts)
    except tokenize.TokenError:
        return code.strip()


# ---------------------------------------------------------------------------
# Similarity scoring
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------------------
# Collect functions
# ---------------------------------------------------------------------------

def collect_functions(source: str, prefix: str | None = None) -> dict[str, tuple[ast.FunctionDef, str, str]]:
    """
    Returns {name: (node, raw_body, normalized_body)} for all matching functions.
    """
    tree = ast.parse(source)
    lines = source.splitlines()
    result: dict[str, tuple[ast.FunctionDef, str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if prefix and not node.name.startswith(prefix):
                continue
            raw = _body_source(node, lines)
            norm = _normalize_tokens(raw)
            result[node.name] = (node, raw, norm)
    return result


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def find_duplicates(
    source: str,
    prefix: str | None = None,
    threshold: float = 0.70,
) -> list[tuple[str, str, float]]:
    """Return list of (name_a, name_b, similarity) pairs above threshold."""
    funcs = collect_functions(source, prefix)
    names = list(funcs.keys())
    pairs: list[tuple[str, str, float]] = []
    for a, b in combinations(names, 2):
        _, _, norm_a = funcs[a]
        _, _, norm_b = funcs[b]
        sim = _similarity(norm_a, norm_b)
        if sim >= threshold:
            pairs.append((a, b, sim))
    pairs.sort(key=lambda t: t[2], reverse=True)
    return pairs


def diff_bodies(name_a: str, name_b: str, funcs: dict) -> str:
    """Show side-by-side diff of two function bodies."""
    import difflib
    _, raw_a, _ = funcs[name_a]
    _, raw_b, _ = funcs[name_b]
    diff = difflib.unified_diff(
        raw_a.splitlines(),
        raw_b.splitlines(),
        fromfile=name_a,
        tofile=name_b,
        lineterm="",
    )
    return "\n".join(diff)


# ---------------------------------------------------------------------------
# Multi-file exact-clone detection  (same algorithm as quality_gate_report.py)
# ---------------------------------------------------------------------------

def _iter_py_files(roots: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            rp = root.resolve()
            if rp not in seen:
                seen.add(rp)
                result.append(rp)
            continue
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            rp = path.resolve()
            if rp not in seen:
                seen.add(rp)
                result.append(rp)
    return result


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _normalized_ast_dump(node: ast.AST) -> str:
    """Normalized, hash-stable dump — identical algorithm to quality_gate_report.py."""
    raw = ast.dump(node)
    raw = re.sub(r"id='[^']*'", "id='v'", raw)
    raw = re.sub(r"arg='[^']*'", "arg='a'", raw)
    raw = re.sub(r"attr='[^']*'", "attr='m'", raw)
    raw = re.sub(r"name='[^']*'", "name='n'", raw)
    raw = re.sub(r"value=[0-9]+\.[0-9]+", "value=0", raw)
    raw = re.sub(r"value=[0-9]+", "value=0", raw)
    raw = re.sub(r"value='[^']*'", "value='s'", raw)
    return raw


def collect_ast_clones(
    py_files: list[Path],
    repo_root: Path,
    min_nodes: int = 15,
) -> list[dict]:
    """Return list of clone-pair dicts using exact AST-hash matching."""
    records: list[dict] = []
    for py_file in py_files:
        try:
            code = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(code)
            rel = _rel(py_file, repo_root)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                body_nodes = list(ast.walk(node))
                if len(body_nodes) < min_nodes:
                    continue
                dump = _normalized_ast_dump(node)
                h = hashlib.sha1(dump.encode(), usedforsecurity=False).hexdigest()  # noqa: S324
                records.append({
                    "file": rel,
                    "name": node.name,
                    "line": node.lineno,
                    "hash": h,
                    "size": len(body_nodes),
                })
        except Exception:
            pass

    by_hash: dict[str, list[dict]] = {}
    for r in records:
        by_hash.setdefault(r["hash"], []).append(r)

    pairs: list[dict] = []
    for group in by_hash.values():
        if len(group) < 2:
            continue
        a, b = group[0], group[1]
        pairs.append({
            "location_a": f"{a['file']}:{a['line']} {a['name']}",
            "location_b": f"{b['file']}:{b['line']} {b['name']}",
            "file_a": a["file"], "name_a": a["name"], "line_a": a["line"],
            "file_b": b["file"], "name_b": b["name"], "line_b": b["line"],
            "clone_count": len(group),
            "body_size": a["size"],
        })
    return sorted(pairs, key=lambda x: (x["clone_count"], x["body_size"]), reverse=True)


def _load_snapshot(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WARNING: could not load {path}: {exc}", file=sys.stderr)
        return None


def _key(pair: dict) -> tuple[str, str]:
    return (pair.get("location_a", ""), pair.get("location_b", ""))


# ---------------------------------------------------------------------------
# Live scan helpers  (mirror quality_gate_report.py logic without the slice)
# ---------------------------------------------------------------------------

def _is_decorator_registered(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when a function has a registration decorator (e.g. @app.route, @cl.on_*)."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            dec = dec.func
        if isinstance(dec, ast.Attribute):
            return True
    return False


def scan_high_param_functions(
    py_files: list[Path], repo_root: Path, max_params: int = 5
) -> list[dict]:
    """Return all public functions with more than max_params parameters."""
    result: list[dict] = []
    for py_file in py_files:
        try:
            code = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(code)
        except Exception:
            continue
        rel = _rel(py_file, repo_root)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue
            if _is_decorator_registered(node):
                continue
            all_args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            n = len(all_args)
            if all_args and all_args[0].arg in ("self", "cls"):
                n = max(0, n - 1)
            if n > max_params:
                result.append({"file": rel, "name": node.name, "line": node.lineno, "params": n})
    return sorted(result, key=lambda x: x["params"], reverse=True)


def scan_unused_functions(
    py_files: list[Path], repo_root: Path
) -> list[dict]:
    """Return all unused top-level functions using find_unused.analyse()."""
    import importlib.util as _ilu
    import sys as _sys
    find_unused_path = Path(__file__).with_name("find_unused.py")
    spec = _ilu.spec_from_file_location("_find_unused_tool", find_unused_path)
    if spec is None or spec.loader is None:
        return []
    mod = _ilu.module_from_spec(spec)
    _sys.modules[spec.name] = mod  # register before exec so dataclass __module__ resolves
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    unused_symbols, _ = mod.analyse(py_files, repo_root, prefix=None)
    return [
        {"name": s.name, "file": s.file, "line": s.line}
        for s in unused_symbols
        if s.kind == "function" and s.owner is None
    ]


# ---------------------------------------------------------------------------
# Full delta report: all 3 regression metrics in one command
# ---------------------------------------------------------------------------

def full_delta_report(
    baseline: dict,
    scan_paths: list[Path],
    repo_root: Path,
) -> None:
    """Live-scan the workspace and show what is new vs the baseline snapshot."""

    py_files = _iter_py_files(scan_paths)
    print(f"Live-scanning {len(py_files)} Python files …")

    # --- Duplicate pairs (AST-hash clones) ---
    live_pairs = collect_ast_clones(py_files, repo_root)
    b_pair_keys = {_key(p) for p in baseline.get("duplicate_blocks", [])}
    new_pairs = [p for p in live_pairs if _key(p) not in b_pair_keys]
    b_count = baseline.get("duplicate_block_pairs", 0)
    print(f"\n=== DUPLICATE CODE PAIRS  (baseline {b_count} → live {len(live_pairs)}, Δ={len(live_pairs) - b_count}) ===")
    if new_pairs:
        print("New pairs since baseline:")
        for p in new_pairs:
            print(f"  {p['clone_count']}× / {p['body_size']} nodes:  "
                  f"{p['file_a']}:{p['line_a']} {p['name_a']}  <->  "
                  f"{p['file_b']}:{p['line_b']} {p['name_b']}")
    else:
        print("  No new pairs detected.")

    # --- High-parameter functions ---
    live_hpf = scan_high_param_functions(py_files, repo_root)
    b_hpf_keys = {(f["name"], f["file"]) for f in baseline.get("high_param_functions", [])}
    new_hpf = [f for f in live_hpf if (f["name"], f["file"]) not in b_hpf_keys]
    b_hpc = baseline.get("high_param_count", 0)
    print(f"\n=== HIGH-PARAMETER FUNCTIONS  (baseline {b_hpc} → live {len(live_hpf)}, Δ={len(live_hpf) - b_hpc}) ===")
    if new_hpf:
        print("New high-param functions since baseline:")
        for f in new_hpf:
            print(f"  {f['params']} params: {f['name']} in {f['file']}:{f['line']}")
    else:
        print("  No new high-param functions detected.")

    # --- Unused functions ---
    live_unused = scan_unused_functions(py_files, repo_root)
    b_unused_keys = {(f["name"], f["file"]) for f in baseline.get("unused_functions", [])}
    new_unused = [f for f in live_unused if (f["name"], f["file"]) not in b_unused_keys]
    b_uc = baseline.get("unused_function_count", 0)
    print(f"\n=== UNUSED FUNCTIONS  (baseline {b_uc} → live {len(live_unused)}, Δ={len(live_unused) - b_uc}) ===")
    if new_unused:
        print("New unused functions since baseline:")
        for f in new_unused:
            print(f"  {f['name']} in {f['file']}:{f['line']}")
    else:
        print("  No new unused functions detected.")
        # --- Truncation note ---
        b_hpf_stored = len(baseline.get("high_param_functions", []))
        b_unused_stored = len(baseline.get("unused_functions", []))
        b_dup_stored = len(baseline.get("duplicate_blocks", []))
        truncated = []
        if b_hpf_stored < b_hpc:
            truncated.append(f"high_param_functions (stored {b_hpf_stored} of {b_hpc})")
        if b_unused_stored < b_uc:
            truncated.append(f"unused_functions (stored {b_unused_stored} of {b_uc})")
        if b_dup_stored < b_count:
            truncated.append(f"duplicate_blocks (stored {b_dup_stored} of {b_count})")
        if truncated:
            print(f"\nNOTE: Baseline snapshot has truncated lists: {', '.join(truncated)}.")
            print("      Set-diff results above may include false positives.")
            print("      Run `python tools/quality_gate_report.py` once to regenerate a complete baseline.")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Find near-duplicate functions in Python source files")
    parser.add_argument("--threshold", type=float, default=0.70,
                        help="Similarity threshold for token-level scan (0–1, default 0.70)")
    parser.add_argument("--prefix", default=None,
                        help="Only compare functions whose names start with this prefix")
    parser.add_argument("--diff", action="store_true",
                        help="Show unified diff for each pair (single-file mode only)")
    parser.add_argument("--file", default=str(TARGET),
                        help=f"Target file for single-file similarity scan (default: {TARGET})")
    parser.add_argument("--multi", action="store_true",
                        help="Scan multiple files using AST-hash exact-clone detection")
    parser.add_argument("paths", nargs="*", default=DEFAULT_SCAN_PATHS,
                        help="Paths to scan in --multi mode (default: src/felvi_games tests)")
    parser.add_argument("--compare-baseline", action="store_true",
                        help="Show only duplicate pairs that are NEW vs the saved quality-gate baseline")
    parser.add_argument("--full-delta", action="store_true",
                        help="Print delta report covering duplicates + high-param fns + unused fns")
    parser.add_argument("--baseline", default=str(BASELINE_PATH),
                        help=f"Baseline snapshot JSON (default: {BASELINE_PATH})")
    parser.add_argument("--current", default=str(CURRENT_PATH),
                        help=f"Current snapshot JSON (default: {CURRENT_PATH})")
    args = parser.parse_args()

    repo_root = Path.cwd()

    # --full-delta: live scan + compare against baseline for all 3 regression metrics
    if args.full_delta:
        baseline = _load_snapshot(Path(args.baseline))
        if not baseline:
            print(f"ERROR: baseline not found at {args.baseline}", file=sys.stderr)
            sys.exit(1)
        scan_roots = [Path(p) for p in args.paths]
        full_delta_report(baseline, scan_roots, repo_root)
        return

    # --multi: AST-hash exact-clone detection across multiple files
    if args.multi or args.compare_baseline:
        scan_roots = [Path(p) for p in args.paths]
        py_files = _iter_py_files(scan_roots)
        print(f"Scanning {len(py_files)} Python files for exact AST clones ...")
        pairs = collect_ast_clones(py_files, repo_root)

        if args.compare_baseline:
            baseline = _load_snapshot(Path(args.baseline))
            if not baseline:
                print(f"WARNING: baseline not found at {args.baseline} — showing all pairs",
                      file=sys.stderr)
            else:
                b_keys = {_key(p) for p in baseline.get("duplicate_blocks", [])}
                b_count = baseline.get("duplicate_block_pairs", 0)
                new_pairs = [p for p in pairs if _key(p) not in b_keys]
                print(f"Baseline: {b_count} pairs  |  Current: {len(pairs)} pairs  "
                      f"|  New: {len(new_pairs)}")
                pairs = new_pairs

        if not pairs:
            print("No duplicate pairs found.")
            return

        print(f"\n{'Clones':>6}  {'Size':>4}  {'Location A':<55} {'Location B'}")
        print("-" * 130)
        for p in pairs:
            loc_a = f"{p['file_a']}:{p['line_a']} {p['name_a']}"
            loc_b = f"{p['file_b']}:{p['line_b']} {p['name_b']}"
            print(f"{p['clone_count']:>6}  {p['body_size']:>4}  {loc_a:<55} {loc_b}")
        return

    # Default: single-file token-level similarity scan
    path = Path(args.file)
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)

    source = path.read_text(encoding="utf-8")
    funcs = collect_functions(source, prefix=args.prefix)
    print(f"Analysing {len(funcs)} functions in {path}")
    print(f"Similarity threshold: {args.threshold:.0%}\n")

    pairs = find_duplicates(source, prefix=args.prefix, threshold=args.threshold)

    if not pairs:
        print("No duplicate pairs found above threshold.")
        return

    print(f"{'Function A':<40} {'Function B':<40} {'Similarity':>10}")
    print("-" * 94)
    for a, b, sim in pairs:
        print(f"{a:<40} {b:<40} {sim:>10.1%}")

    if args.diff:
        for a, b, sim in pairs:
            print(f"\n{'='*70}")
            print(f"DIFF: {a} vs {b}  (similarity {sim:.1%})")
            print("=" * 70)
            print(diff_bodies(a, b, funcs))


if __name__ == "__main__":
    main()
