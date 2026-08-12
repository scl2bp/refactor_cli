# refactor-cli

Deterministic structural refactoring for Python projects.

`refactor-cli` lets an engineer or an LLM-driven agent plan structural code changes against a persistent project tree, then apply those changes through a controlled workflow instead of editing source files directly. It is designed for iterative refactoring where you want explicit intent, reproducible moves, and built-in validation.

## What It Does

- scans a Python project and writes a structural tree to `.refactor/tree.yaml`
- accepts structural change requests as either a tree diff patch or a line-number-free tree edit YAML
- derives symbol moves and file deletions from the requested tree change
- applies those changes to source files using either an internal backend or Emend
- runs safeguards on affected files: format, autoimport, compile, and lint
- regenerates the tree from actual code and verifies the result
- archives applied patch/edit files for traceability

This makes it useful for:

- incremental modularization of large Python files
- LLM-assisted refactoring with explicit intermediate artifacts
- low-level structural edits that need deterministic verification

## Installation

### Local editable install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs the `refactor-cli` command and the runtime dependencies declared in [pyproject.toml](pyproject.toml).

### Install into an existing virtual environment

```bash
/path/to/venv/bin/python -m pip install -e /path/to/refactor_cli
```

Example:

```bash
/workspace/mobiliti/.venv/bin/python -m pip install -e /workspace/refactor_cli
```

### Run without a prior install using uvx

```bash
uvx --from /workspace/refactor_cli refactor-cli --help
```

## Runtime Requirements

The tool validates required runtime tools before executing apply workflows.

Required Python packages:

- `libcst`
- `pyyaml`
- `ruff`
- `autoimport`
- `emend`

Supported Emend invocation modes:

1. `uvx emend`
2. `emend`
3. `python -m emend`

## Command Surface

After installation, use either:

```bash
refactor-cli --help
```

or:

```bash
python -m refactor_cli --help
```

Available commands:

- `init`
- `files`
- `tree`
- `format`
- `apply-tree-patch`
- `apply-tree-edit`

## Quick Start

### 1. Initialize project metadata

Run this in the target repository where you want to perform structural refactors:

```bash
refactor-cli init
```

This creates `.refactor/config.json`.

### 2. Configure which files belong to the project surface

Example config:

```json
{
  "project_root": "..",
  "python_files": {
    "include": ["main.py", "src/**/*.py", "tests/**/*.py", "tools/**/*.py"],
    "exclude": [".venv/**", "**/__pycache__/**", "build/**", "dist/**"]
  }
}
```

### 3. Generate the structural tree

```bash
refactor-cli tree
```

This writes `.refactor/tree.yaml`.

### 4. Describe the intended structural change

Preferred format for LLM-driven workflows: `.refactor/patches/latest.tree.edit.yaml`

Example:

```yaml
version: 1
moves:
  - source: src/app/main.py
    target: src/app/parsers.py
    symbols:
      - parse_user
      - parse_order
delete_files:
  - src/app/legacy.py
```

### 5. Apply the structural change

```bash
refactor-cli apply-tree-edit
```

The tool will:

1. build the intended target tree from the edit YAML
2. detect moved symbols and deleted files
3. apply the code changes
4. run safeguards on affected files
5. regenerate `.refactor/tree.yaml`
6. verify that the resulting code matches the requested structure
7. archive the applied edit in `.refactor/patches/applied/`

## LLM Agent Quick Start

The easiest reliable workflow for an LLM-based agent is:

1. run `refactor-cli tree`
2. inspect `.refactor/tree.yaml`
3. decide on a small structural move
4. write `.refactor/patches/latest.tree.edit.yaml`
5. run `refactor-cli apply-tree-edit`
6. inspect the updated tree and rerun with the next small move

Guidelines for agents:

- prefer `apply-tree-edit` over unified diff patches when possible
- move one cohesive slice at a time
- let the tool derive file edits from tree intent rather than rewriting code manually
- rely on the built-in safeguards, but still run a project-specific smoke test after major refactors
- regenerate the tree before creating a new patch if the code has changed outside the tool

## `.refactor/` Workspace

| Path | Purpose |
|---|---|
| `.refactor/config.json` | project discovery config |
| `.refactor/tree.yaml` | current structural tree |
| `.refactor/patches/latest.tree.patch.yaml` | unified diff style tree patch |
| `.refactor/patches/latest.tree.edit.yaml` | line-number-free structural edit request |
| `.refactor/patches/applied/` | archived applied patch/edit files |

## Patch Formats

### Tree edit YAML

Recommended for LLM-generated changes.

```yaml
version: 1
moves:
  - source: path/to/source.py
    target: path/to/target.py
    symbols:
      - SymbolA
      - SymbolB
delete_files:
  - path/to/obsolete.py
```

### Tree patch diff

Supported through `apply-tree-patch` when you want to transform the tree file directly via a unified diff.

## Safeguards

After apply, the tool runs affected-file safeguards:

1. `ruff format`
2. `autoimport`
3. `python -m py_compile`
4. `ruff check --select F821,F401,E902`

The package also performs runtime dependency preflight before apply commands.

## Typical Commands

```bash
refactor-cli init
refactor-cli files
refactor-cli tree --print
refactor-cli format
refactor-cli apply-tree-edit
refactor-cli apply-tree-patch
```

## Troubleshooting

`Tool fails to parse a Python file`

Run:

```bash
python -m py_compile path/to/file.py
```

`Tree patch hunk context not found`

Regenerate the tree before creating a new patch:

```bash
refactor-cli tree
```

`Verification failed after apply`

Check whether the requested symbols still exist in the source file and whether the intended target tree still matches the live codebase.

`Emend backend requested but not found`

Install one of the supported Emend runners:

- `uv` for `uvx emend`
- `emend` CLI
- Python package `emend`

## Development Notes

The codebase is being refactored incrementally toward higher cohesion and lower coupling. The active plan is documented in [docs/refactoring-plan.md](docs/refactoring-plan.md).

For architectural constraints and SWE guidance, see [docs/swe.md](docs/swe.md).