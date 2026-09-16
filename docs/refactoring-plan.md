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

Status:

- complete

### Phase 2: Persistence and Tree Codec Extraction

Extract JSON/YAML helpers and compact tree serialization to dedicated modules.

Scope:

- `file_io.py`
  - `ensure_parent`
  - `load_json`
  - `write_json`
  - `load_yaml`
  - `write_yaml`
  - `yaml_text`
  - `archive_patch`
- `tree_codec.py`
  - `_node_to_compact`
  - `_compact_to_node`
  - `write_tree_yaml`
  - `load_tree_yaml`

Expected outcome:

- persistence concerns move out of the workflow module
- tree document encoding/decoding becomes a dedicated boundary
- `__init__.py` becomes more orchestration-focused without changing behavior

Validation:

- `python -m py_compile src/refactor_cli/__init__.py src/refactor_cli/file_io.py src/refactor_cli/tree_codec.py src/refactor_cli/runtime_tools.py src/refactor_cli/__main__.py`
- `PYTHONPATH=src python -m refactor_cli tree`
- `PYTHONPATH=src python -m refactor_cli --help`

Status:

- complete

### Phase 3: Discovery Extraction

Extract config loading, path resolution, Python file discovery, CST loading, and tree generation.

Scope:

- `load_config`
- `resolve_project_root`
- `discover_python_files`
- `load_module`
- `statement_name`
- `is_import_statement`
- `render_statements`
- `build_tree`
- `print_tree`
- `generate_tree_payload`

Expected outcome:

- project scanning and CST tree generation move behind a dedicated module boundary
- orchestration code stops owning discovery concerns directly

Validation:

- `python -m py_compile src/refactor_cli/__init__.py src/refactor_cli/discovery.py src/refactor_cli/runtime_tools.py src/refactor_cli/file_io.py src/refactor_cli/tree_codec.py src/refactor_cli/__main__.py`
- `PYTHONPATH=src python -m refactor_cli files`
- `PYTHONPATH=src python -m refactor_cli tree`
- `PYTHONPATH=src python -m refactor_cli --help`

Status:

- complete

### Phase 4: Safeguards Extraction

Extract the post-apply validation pipeline into a dedicated safeguards module.

Scope:

- `post_apply_safeguards`

Expected outcome:

- affected-file validation becomes a dedicated workflow boundary
- orchestration code depends on safeguards rather than implementing them inline

Validation:

- `python -m py_compile src/refactor_cli/__init__.py src/refactor_cli/safeguards.py src/refactor_cli/discovery.py src/refactor_cli/runtime_tools.py src/refactor_cli/file_io.py src/refactor_cli/tree_codec.py src/refactor_cli/__main__.py`
- `PYTHONPATH=src python -m refactor_cli --help`
- `PYTHONPATH=src python -m refactor_cli tree`

### Phase 5: Typed Model Introduction

Replace implicit dictionary contracts for tree documents, operations, and edits with typed models.

### Phase 6: Move Backend Separation

Separate internal and Emend move backends behind composable interfaces or adapter functions.

### Phase 7: Transition Workflow Extraction

Move tree delta interpretation and apply/verify orchestration into a dedicated workflow module.

### Phase 8: Thin CLI Shell

Move parser and command handlers into `cli.py`, leaving `__init__.py` as a small export surface.

## Feature Evaluation and Refinement

The features were re-evaluated one by one from a clean state on 2026-09-16. The
configured scope was `src/refactor_cli`; `.eval` was excluded from dependency
qualified-name queries. The order below follows the actual information flow.

### Chapter 1: Configured file discovery

**Feature description:** `files` resolves the project root and applies the include
and exclude rules from `.refactor/config.json`.

**Command and options:**

```bash
refactor-cli files --config .refactor/config.json
```

**Generated files:** None. The command is read-only.

**Generated-file description:** The terminal output reports the resolved project
root and discovered Python files.

**Usefulness evaluation:** Essential and reliable. It discovered 18 Python files,
which became the input for every later evaluation.

**Improvement suggestion:** Add `--format json` with included files, excluded files,
and counts so downstream features can consume a recorded discovery manifest.

### Chapter 2: Structural tree analysis

**Feature description:** `tree` converts the discovered Python source into a
persistent top-level structural inventory used to plan and verify moves.

**Command and options:**

```bash
refactor-cli tree --config .refactor/config.json \
  --output .refactor/tree.yaml --print
```

**Generated files:** `.refactor/tree.yaml`.

**Generated-file description:** Compact YAML containing 18 files and their modules,
functions, classes, constants, and other top-level nodes.

**Usefulness evaluation:** High. It is reviewable, deterministic, and provides the
structural contract checked after `apply-tree-edit` or `apply-tree-patch`.

**Improvement suggestion:** Validate the tree schema/version and add a compact JSON
summary of node counts for easier baseline comparison.

### Chapter 3: Native quality report

**Feature description:** `quality-report` performs local AST analysis without CBM.
It calculates imports, fan-in/fan-out, cycles, dependency paths, complexity,
normalized duplicate groups, unused public functions, and high-fan-out move
candidates.

**Command and options:**

```bash
refactor-cli quality-report \
  --config .refactor/config.json \
  --scope-path src/refactor_cli \
  --output-dir .refactor/analysis/quality
```

**Generated files:** `.refactor/analysis/quality/quality.json` and
`.refactor/analysis/quality/quality.md`.

**Generated-file description:** JSON contains machine-readable findings. Markdown
renders dependency tables, cycles, paths, Mermaid, source links, complexity
hotspots, duplicates, and unused functions.

**Usefulness evaluation:** High for fast, provider-independent refactoring triage.
The clean run found 18 modules, no parse errors, 7 move candidates, 0 duplicate
groups, and 66 unused public-function findings. The metrics are useful signals but
not release-quality gates.

**Improvement suggestion:** Add baseline comparison, cyclomatic complexity,
maintainability metrics, and regression statuses.

### Chapter 4: Candidate Phase A analysis

**Feature description:** `candidate-phase-a` runs Codebase Memory adapters for
source indexing, dependency extraction, semantic retrieval, and architecture
overview. Optional CodeRAG validation can also be enabled.

**Command and options:**

```bash
refactor-cli candidate-phase-a --config .refactor/config.json
```

Configuration controls project name, CBM binary, index mode, scope, qualified-name
prefix, semantic terms, result limit, exclusions, output directory, and the
optional `--include-coderag-validate` flag.

**Generated files:**

- `.refactor/analysis/candidates/source_index.json`
- `.refactor/analysis/candidates/dependency_graph.json`
- `.refactor/analysis/candidates/semantic_retrieval.json`
- `.refactor/analysis/candidates/architecture_report.json`
- `.refactor/analysis/candidates/summary.json`
- optional `.refactor/analysis/candidates/coderag_validate.json`

**Generated-file description:** The source index records coverage and parse health;
the dependency graph stores `CALLS`, `IMPORTS`, and `INHERITS` rows; semantic
retrieval stores ranked/grouped hits; architecture reports hotspots, clusters,
entry points, and graph counts; summary records adapter status.

**Usefulness evaluation:** High when CBM is available. All enabled adapters were
`OK`. The scoped architecture view contained 205 nodes and 539 edges, but the
underlying index contained 45,392 nodes and 194,841 edges with 60 partial parses.

**Improvement suggestion:** Isolate the indexed corpus to the configured source
scope, filter excluded paths before semantic ranking, and report discarded rows.

### Chapter 5: Candidate report

**Feature description:** `candidate-report` consolidates the Phase A artifacts into
a human-readable architecture and readiness report.

**Command and options:**

```bash
refactor-cli candidate-report --config .refactor/config.json
```

Use `--input-dir` and `--output` to override the configured candidate artifact
directory and report path.

**Generated files:** `.refactor/analysis/candidates/report.md`.

**Generated-file description:** Markdown with module status, artifact sizes, raw
artifact interpretation, Mermaid diagrams, readiness, index health, and findings.

**Usefulness evaluation:** High for human review and handoff. The clean run
generated a 382-line report and clearly marked CodeRAG as `SKIP` because it was
disabled.

**Improvement suggestion:** Add stable section identifiers, finding counts, and a
report-diff mode for comparing evaluation runs.

### Chapter 6: Focused candidate search

**Feature description:** `candidate-search` answers a focused semantic or graph
question without rebuilding the complete Phase A artifact set.

**Command and options:**

```bash
refactor-cli candidate-search \
  --config .refactor/config.json \
  --semantic-query 'dependency,module,quality metrics' \
  --label Function --limit 20
```

Other useful options are `--profile`, `--scope-path`, `--scope-qn-prefix`,
`--file-pattern`, `--format json|tree`, and `--cbm-options`.

**Generated files:** None by default; JSON is printed to the terminal.

**Generated-file description:** The result contains grouped structural matches and
semantic rows with names, labels, source files, scores, and graph degree data.

**Usefulness evaluation:** High for interactive investigation. The clean run found
157 total matches and returned 20 rows. Semantic results still included `.eval`
paths, so they require review before driving an automated move.

**Improvement suggestion:** Apply path/QN exclusions to semantic rows, add an
`--output` option, and save query metadata alongside results.

### Evaluation conclusion and next order

The most valuable immediate refinement is corpus isolation because it affects both
Phase A semantic retrieval and focused search. After that, add quality baselines,
feature-level artifact tests, optional CodeRAG evaluation, stronger native metrics,
and continued extraction of the remaining CLI/config/workflow code from
`__init__.py`. Each refinement should repeat the six chapters from a clean output
directory and compare the generated artifacts with the previous baseline.

## Working Rules

- change one cohesive slice at a time
- validate immediately after each slice
- avoid behavior changes while extracting structure
- do not introduce generic catch-all utility modules