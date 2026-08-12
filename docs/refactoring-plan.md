# Refactoring Plan

## Goals

This refactoring follows the SWE guidance in [docs/swe.md](docs/swe.md):

- high cohesion: each module should own one responsibility
- low coupling: workflow layers should depend on lower-level services, not the reverse
- composition over branching: move backends and safeguards should be composed into the workflow

The current implementation in `src/refactor_cli/__init__.py` mixes package entrypoint, CLI, tree serialization, CST analysis, workflow orchestration, and runtime tool execution. The path below separates those concerns incrementally while preserving behavior after each phase.

## Target Architecture

- `src/refactor_cli/__init__.py`
  - stable package export only
- `src/refactor_cli/__main__.py`
  - module launcher only
- `src/refactor_cli/runtime_tools.py`
  - runtime dependency detection and subprocess wrappers
- `src/refactor_cli/file_io.py`
  - JSON/YAML helpers and archive helpers
- `src/refactor_cli/tree_codec.py`
  - compact tree read/write and tree document conversions
- `src/refactor_cli/discovery.py`
  - config loading, file discovery, CST loading, tree generation
- `src/refactor_cli/diff_apply.py`
  - unified diff application and tree-edit transforms
- `src/refactor_cli/safeguards.py`
  - format, autoimport, compile, lint workflow
- `src/refactor_cli/movers/internal.py`
  - LibCST symbol extraction backend
- `src/refactor_cli/movers/emend.py`
  - Emend symbol extraction backend
- `src/refactor_cli/transition.py`
  - apply-and-verify workflow orchestration
- `src/refactor_cli/cli.py`
  - parser and command handlers

## Phases

### Phase 1: Runtime Tool Extraction

Extract runtime dependency checks and subprocess-based tool execution into `runtime_tools.py`.

Scope:

- `_python_module_available`
- `resolve_emend_runner`
- `ensure_runtime_dependencies`
- `run_formatter_on_file`
- `run_compile_check_on_file`
- `run_autoimport_on_file`
- `run_lint_check_on_file`
- `_run_ruff_fix_imports`

Expected outcome:

- `__init__.py` keeps orchestration behavior but no longer owns runtime tool implementation
- runtime requirements remain explicit and testable in one place

Validation:

- `python -m py_compile src/refactor_cli/__init__.py src/refactor_cli/runtime_tools.py src/refactor_cli/__main__.py`
- `PYTHONPATH=src python -m refactor_cli --help`
- `PYTHONPATH=src python -c "import refactor_cli as r; r.ensure_runtime_dependencies(require_emend=True)"`

### Phase 2: Persistence and Tree Codec Extraction

Extract JSON/YAML helpers and compact tree serialization to dedicated modules.

### Phase 3: Discovery Extraction

Extract config loading, path resolution, Python file discovery, CST loading, and tree generation.

### Phase 4: Typed Model Introduction

Replace implicit dictionary contracts for tree documents, operations, and edits with typed models.

### Phase 5: Move Backend Separation

Separate internal and Emend move backends behind composable interfaces or adapter functions.

### Phase 6: Transition Workflow Extraction

Move tree delta interpretation and apply/verify orchestration into a dedicated workflow module.

### Phase 7: Thin CLI Shell

Move parser and command handlers into `cli.py`, leaving `__init__.py` as a small export surface.

## Working Rules

- change one cohesive slice at a time
- validate immediately after each slice
- avoid behavior changes while extracting structure
- do not introduce generic catch-all utility modules