# Refactoring Tools

## Overview

CLI tools in `tools/` provide deterministic, project-agnostic structural refactoring driven by LibCST and a project config. The primary tool is `structural_refactor.py`, which works from a persistent structural tree (`tree.yaml`) and a diff patch file rather than editing source code directly.

## Core Tools

### `structural_refactor.py` — Structural Refactoring Engine

Project-agnostic. Reads project layout from `.refactor/config.json`. All commands default to that config with no required arguments.

#### `init`
Create a default `.refactor/config.json`.

```bash
python tools/structural_refactor.py init
```

#### `files`
List Python files discovered from config.

```bash
python tools/structural_refactor.py files
```

#### `tree`
Scan all configured Python files and write the structural tree to `.refactor/tree.yaml`.

```bash
python tools/structural_refactor.py tree
# optional: also print to stdout
python tools/structural_refactor.py tree --print
```

#### `apply-tree-patch`
Full end-to-end pipeline from a tree diff patch to applied code changes:
1. Apply the patch to a temporary copy of the tree
2. Diff before/after tree to derive internal change request (symbol moves, file deletions)
3. Apply changes to project source files
4. Regenerate `tree.yaml` from actual code
5. Verify result matches intended tree
6. Remove temp file and patch file

```bash
python tools/structural_refactor.py apply-tree-patch
```

Use `--keep-patch` to retain the patch file after apply.

---

### `refactor_cli.py` — Analysis Interface

LibCST-based code structure analysis. Useful for inspecting a file before writing a config operation.

```bash
python tools/refactor_cli.py show-structure main.py
python tools/refactor_cli.py extract-constants main.py
```

---

### `status.py` — Validation Dashboard

Runs baseline checks (tests, linting, type checking) and reports readiness.

```bash
python tools/status.py
```

---

## Supporting Modules

### `extractors.py`
LibCST visitor classes used by `refactor_cli.py`: `ConstantExtractor`, `CodeStructureAnalyzer`.

### `diff_generator.py`
Utilities for generating unified diffs between text versions.

---

## Configuration: `.refactor/config.json`

Drives file discovery and operations. Generate a starter with `init`, then customise.

```json
{
  "project_root": "..",
  "python_files": {
    "include": ["main.py", "src/**/*.py", "tests/**/*.py"],
    "exclude": [".venv/**", "**/__pycache__/**"]
  },
  "default_operation": "my_extract",
  "operations": {
    "my_extract": {
      "type": "extract_top_level_symbols",
      "source": "main.py",
      "target": "src/mypackage/domain.py",
      "symbols": ["ClassA", "ClassB", "CONST_X"],
      "source_import_block": "from mypackage.domain import ClassA, ClassB, CONST_X",
      "target_prelude": [
        "\"\"\"Domain module.\"\"\"",
        "",
        "from __future__ import annotations"
      ]
    }
  }
}
```

---

## Standard Workflow

```bash
# 1. Scan project and write tree.yaml
python tools/structural_refactor.py tree

# 2. Inspect the tree
cat .refactor/tree.yaml

# 3. Write (or let an LLM generate) a unified diff patch for the intended structural change
# -> .refactor/patches/latest.tree.patch.yaml

# 4. Apply the patch: moves symbols / deletes files, updates tree, verifies
python tools/structural_refactor.py apply-tree-patch

# 5. Run tests
python -m pytest tests/
```

---

## `.refactor/` Workspace

| Path | Description |
|---|---|
| `.refactor/config.json` | Project config and operations |
| `.refactor/intent.json` | Optional: override which operation runs by default |
| `.refactor/tree.yaml` | Persistent structural tree of all configured Python files |
| `.refactor/patches/` | Generated patch files (removed after apply) |

---

## Supported Operation Types

### `extract_top_level_symbols`
Moves named top-level symbols (classes, functions, constants) from a source file to a target file, inserting an import block into the source.

Config fields:
- `source` — relative path of the file to extract from
- `target` — relative path of the new module to create
- `symbols` — list of top-level symbol names to move
- `source_import_block` — import statement(s) to insert into source after removal
- `target_prelude` — lines to prepend to the generated target file (docstring, imports)

---

## Troubleshooting

**Tool fails to parse a Python file** — check for syntax errors: `python -m py_compile <file>`

**Tree patch hunk context not found** — regenerate the tree (`tree` command) before generating a new patch; a stale tree will cause mismatches.

**Verification failed after apply** — the regenerated tree doesn't match the patched tree. Check that all symbols listed in the operation are present in the source file before running.

**Tests fail after extraction** — verify import paths are correct and all dependencies are included in `target_prelude`.

---

## Related Files

- `.refactor/config.json` — project operations config
- `.refactor/tree.yaml` — current structural tree
- `pyproject.toml` — project dependencies
- `tests/test_merged_cli.py` — baseline regression tests
