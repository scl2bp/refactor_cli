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

## Feature Evaluation

The analysis and quality features were evaluated against the current `refactor-cli`
source tree on 2026-09-16. The configured scope was `src/refactor_cli`, with
`.eval` excluded from dependency qualified-name results.

### Evaluation commands

Run these commands from the repository root:

```bash
refactor-cli files
refactor-cli tree --print
refactor-cli quality-report \
  --config .refactor/config.json \
  --scope-path src/refactor_cli \
  --output-dir .refactor/analysis/quality
refactor-cli candidate-phase-a --config .refactor/config.json
refactor-cli candidate-report --config .refactor/config.json
refactor-cli candidate-search \
  --config .refactor/config.json \
  --semantic-query 'dependency,module,quality metrics' \
  --label Function \
  --limit 20
```

### Generated evaluation files

| File | Feature | Evaluation value |
|---|---|---|
| `.refactor/tree.yaml` | Structural tree | Persistent inventory used to plan and verify moves |
| `.refactor/analysis/quality/quality.json` | Native quality | Machine-readable dependencies, complexity, duplicates, unused functions, and move candidates |
| `.refactor/analysis/quality/quality.md` | Native quality | Human-readable quality findings |
| `.refactor/analysis/candidates/source_index.json` | Source indexing | Index coverage, exclusions, node/edge counts, and parse warnings |
| `.refactor/analysis/candidates/dependency_graph.json` | Dependency graph | Scoped raw `CALLS`, `IMPORTS`, and `INHERITS` edges |
| `.refactor/analysis/candidates/semantic_retrieval.json` | Semantic retrieval | Ranked and grouped discovery results |
| `.refactor/analysis/candidates/architecture_report.json` | Architecture report | Hotspots, clusters, entry points, and graph summaries |
| `.refactor/analysis/candidates/summary.json` | Phase A orchestration | Module-level `OK`, `FAIL`, or `SKIP` status |
| `.refactor/analysis/candidates/report.md` | Candidate report | Consolidated interpretation of all Phase A artifacts |

`candidate-search` prints focused JSON to the terminal and does not create an
artifact unless its output is redirected by the caller.

### Results and interpretation

| Feature | Result | Assessment |
|---|---|---|
| Configured file discovery | 18 Python files | Reliable project-scope input |
| Structural tree | 18 files; root reduced to 16 top-level nodes | Good planning and post-refactor verification boundary |
| Native quality report | 18 modules, no parse errors, 7 move candidates, 0 duplicate groups, 66 unused public functions | Useful local baseline; heuristics need trend tracking before being treated as gates |
| Source index | `OK`; 45,392 indexed nodes and 194,841 indexed edges; 60 partial parses reported | Operationally successful, but the index is much broader than the package scope |
| Scoped architecture report | 205 nodes and 539 edges; 157 functions; 217 calls; 80 imports | Strongest high-level architecture view |
| Scoped dependency graph | `OK`; 455 returned edge rows | Useful for concrete relationship inspection |
| Semantic retrieval | `OK`; 204 matching structural entries in the Phase A artifact | Helpful for discovery, but rankings are affected by corpus noise |
| Candidate report | 379-line Markdown report | Good artifact for human inspection and handoff |
| Focused candidate search | `OK`; 157 total matches, 20 returned | Useful interactively; semantic results included `.eval` entries and require filtering |
| CodeRAG validation | `SKIP` | Disabled by configuration, therefore unevaluated |

### Refinement plan

1. **Isolate the indexed corpus.** Ensure Codebase Memory indexing honors the
  configured source scope and does not expose `.eval` or vendored evaluation data
  to semantic ranking. Add a regression fixture that fails when an excluded path
  appears in candidate output.
2. **Make scope filtering consistent.** Apply the same path and qualified-name
  filtering to source indexing, semantic retrieval, architecture summaries, and
  `candidate-search`, then report the number of discarded rows.
3. **Add quality baselines.** Support a checked-in baseline and a comparison mode
  for complexity, fan-in/fan-out, duplicate groups, unused functions, parse errors,
  and cycle count. Report regressions separately from informational findings.
4. **Improve native metrics.** Add Radon-style cyclomatic complexity and
  maintainability indicators, while retaining the current dependency and move
  signals as the refactoring-specific layer.
5. **Strengthen duplicate and unused analysis.** Add token-level duplicate detection,
  import-aware symbol references, and explicit dynamic-registration adapters rather
  than relying only on the current conservative AST heuristics.
6. **Evaluate optional providers explicitly.** Add a documented CodeRAG evaluation
  run and distinguish `SKIP`, `UNAVAILABLE`, `FAIL`, and `OK` in the readiness
  summary.
7. **Add feature tests around artifacts.** Validate JSON schemas, report sections,
  source links, Mermaid syntax, scope exclusions, and stable status values in
  focused tests.
8. **Continue structural extraction.** Move the remaining candidate settings and
  orchestration from `__init__.py` into the CLI/config/workflow boundaries using
  one cohesive `refactor-cli apply-tree-edit` operation at a time.

The next highest-value refinement is corpus isolation. The evaluation shows that
the analysis algorithms work, but semantic ranking cannot yet be treated as a clean
refactoring recommendation until excluded evaluation data is removed or filtered
at the indexing boundary.

## Working Rules

- change one cohesive slice at a time
- validate immediately after each slice
- avoid behavior changes while extracting structure
- do not introduce generic catch-all utility modules