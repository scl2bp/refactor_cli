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

Each chapter distinguishes feature behavior, observed evidence, and assessment.
The run used the checked-out repository, the current `.refactor/config.json`, and
empty analysis output directories. Counts are observations from that run, not
expected values or acceptance thresholds. Commands were executed automatically;
tree output, JSON artifacts, and Markdown reports were then inspected manually.
The analysis commands do not modify source files. Tree and report commands write
generated artifacts, whose timestamps, ordering, provider versions, and external
index state may prevent stable byte-for-byte diffs.

### Evaluation protocol

The following provenance must be captured for every repeatable evaluation:

- repository path and commit ID
- working-tree status, including whether source changes were present
- Python version and installed package versions
- Codebase Memory and optional-provider versions
- exact `.refactor/config.json` contents or a SHA-256 hash of the file
- whether analysis output directories were empty before the run
- command, options, exit code, and generated artifact paths

The earlier baseline records the date, repository, configuration, clean output
directories, commands, exit behavior, and artifact paths, but does not yet record
all version and commit metadata. Therefore its numeric results are reproducible in
principle, not a fully pinned experiment.

Known provenance gap: the baseline does not identify a commit ID, working-tree
status, Python/package lock state, or CBM build/version. Those values must be
captured before treating a future rerun as a comparable measurement.

For an objectively successful run, apply these checks in addition to reading the
terminal output:

1. Every command exits with code `0`; an intentional optional skip is reported as
  `SKIP`, not mistaken for `OK`.
2. Every expected JSON artifact parses, contains its documented top-level fields,
  and has the expected provider/status metadata.
3. Tree file count, quality-report file count, and source-index staged-file count
  agree with the configured scope, subject to explicitly reported exclusions.
4. Report counts can be traced back to the JSON payloads; source links point to
  existing files; Mermaid blocks have the expected opening and closing fences.
5. Negative cases are treated as acceptance tests: invalid config, syntax errors,
  missing CBM, malformed candidate JSON, empty search results, include/exclude
  collisions, and partial indexing must produce a clear error, failure status, or
  explicit empty result rather than a false `OK`.

The current baseline performed the first four checks only partially through manual
artifact inspection and did not run the negative cases. Those are evaluation gaps,
not claims that the failure behavior is correct.

### Data flow and authority

`files` defines the configured source boundary. `tree` creates the structural
inventory used for planning and verification. `quality-report` performs local,
provider-independent analysis over that scope. `candidate-phase-a` adds external
index, dependency, semantic, and architecture signals. `candidate-report` presents
those Phase A artifacts; `candidate-search` is an interactive follow-up query.

The native quality report is authoritative only for what its local AST heuristics
calculate. Phase A `source_index` is authoritative for index health, scoped graph
artifacts are authoritative for returned relationships, and semantic results are
discovery hints. No feature currently provides enough evidence to authorize an
automated refactoring move without human review.

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

**Intended user and decision:** Developer or LLM agent; decide whether the configured
project boundary is correct before trusting later analysis. Required as the first
scope check, not a CI quality gate.

**Success/failure:** Success means the resolved root and included files match the
intended project. Failure means an expected file is missing or an excluded/generated
file is present. Include/exclude conflicts are resolved by the discovery
implementation, but the command exposes only included files, so exclusion behavior
is verified by comparing the output with the configured patterns and filesystem.

**Observed result:** 18 Python files were discovered. This is reproducible with the
documented command for the same repository state and configuration, not an expected
count for all projects. The output was manually checked and later commands consumed
the same scope.

**Assessment and open questions:** Reliable as an input check. Open questions are
whether overlapping patterns and unreadable files need explicit diagnostics.

**Representative task and severity:** A user should be able to confirm that
`src/refactor_cli` is included and `.eval` is not. A wrong boundary is **blocking**
for every downstream analysis; missing exclusion diagnostics are a **convenience**
issue until they cause contamination.

**Improvement suggestion (convenience, then provenance):** Add `--format json` with
the resolved root, include/exclude patterns, selected files, excluded files with
reasons, and a configuration hash. This should remain a read-only manifest and
become the recorded scope input for downstream reports.

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

**Intended user and decision:** Developer or LLM agent; decide which symbols can be
moved and whether an applied edit matches the requested structure. Required for the
tree-edit workflow; optional for standalone quality analysis.

**Success/failure:** Success means configured files and relevant top-level nodes are
represented and post-apply verification matches the requested tree. Failure means a
parse error, missing/misclassified node, or failed tree comparison. The compact tree
intentionally omits a full AST, call graph, type model, local nested symbols, and
runtime behavior.

**Observed result:** The run generated an 18-file tree. It was manually inspected
and automatically regenerated by the CLI. The YAML is reproducible for unchanged
source/configuration, although ordering or formatter changes may affect diffs.

**Assessment and open questions:** Strong planning and verification boundary. Open
questions cover syntax-error reporting and which omitted constructs should become
explicitly represented.

**Representative task and severity:** An LLM agent should identify two top-level
symbols suitable for a proposed move and verify their destination after an edit.
Tree omission or misclassification is **blocking** for structural automation;
omission of nested/runtime details is **acceptable for exploration**.

**Improvement suggestion (blocking correctness):** Validate the tree schema and
version, record source/config metadata and parse errors, and emit deterministic
file/node ordering. A compact JSON count summary is useful later, but should follow
schema validation and deterministic output rather than replace them.

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

**Intended user and decision:** Developer or CI-adjacent refactoring workflow;
decide which architectural areas merit inspection. Required when provider-independent
analysis is needed, optional as a supplement to CBM, and not a release gate.

**Success/failure:** Success means the scope parses and JSON/Markdown are written.
Failure means parse errors or report-generation errors. Unused-function findings
can be false positives for public APIs, reflection, plugins, callbacks, exports,
and dynamic registration. Move candidates are fan-out heuristics, and normalized
AST duplicate detection can miss semantic/token clones.

**Observed result:** 18 modules, no parse errors, 7 move candidates, 0 duplicate
groups, and 66 unused public-function findings. These were automatically calculated
and manually reviewed; they are one-run observations, not expected thresholds.

**Assessment and open questions:** Useful for triage, not a quality gate. Open
questions are revision-to-revision stability and false-positive rates on dynamic
Python code.

**Representative task and severity:** A developer should use fan-out and complexity
rows to choose one module for inspection, then confirm it manually. False positives
are **acceptable for exploration** but **blocking for automated cleanup**.

**Improvement suggestion (evaluation correctness first):** Add a checked-in baseline
comparison with explicit regression status for parse errors, cycles, fan-in/fan-out,
duplicates, unused functions, and move candidates. Treat cyclomatic complexity and
maintainability metrics as separate follow-up work to avoid mixing baseline
regression detection with metric expansion.

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

**Intended user and decision:** Developer or LLM agent; decide which modules,
relationships, and architectural areas deserve inspection. Optional/experimental
relative to the native report; it requires the configured CBM executable.

**Success/failure:** `OK` means the adapter completed with a usable payload, not
that every file parsed perfectly. `FAIL` means an error or unusable payload; `SKIP`
means disabled or out of scope. When outputs disagree, index health is the trust
check, scoped dependency/architecture data is structural evidence, and semantic
retrieval is discovery evidence rather than authority. CodeRAG is optional; Emend
is not required because this feature is read-only.

**Observed result:** All enabled adapters were `OK`; the scoped architecture view
had 205 nodes and 539 edges, while the broad index had 45,392 nodes, 194,841 edges,
and 60 partial parses. Artifacts were automatically produced and manually reviewed.

**Assessment and open questions:** Richer than native AST analysis, but not safe for
automated moves until corpus isolation is fixed. Open questions are how partial
parses should affect status and whether excluded paths can be removed before ranking.

**Representative task and severity:** A developer should use the architecture report
to locate the central coordination modules and then inspect dependency edges. Broad
index contamination is **blocking for automation** but **acceptable for manual
exploration** when the source index health is reviewed.

**Improvement suggestion (highest-priority technical fix):** Isolate the corpus at
index creation where the provider supports it, apply post-index filtering as a
safety net, report discarded rows and their reasons, and warn or fail when results
escape the configured scope. Add an acceptance test proving that `.eval` and
vendored paths cannot appear in scoped semantic or graph results.

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

**Intended user and decision:** Developer, reviewer, or LLM agent; decide which raw
artifact or finding to inspect next. It is a presentation layer, not an independent
analyzer or CI gate.

**Success/failure:** Success means available statuses, sizes, interpretations, and
diagrams render without inventing findings. Missing or malformed inputs should be
visible as unavailable/failure states. The report does not adjudicate provider
conflicts; recommendations are interpretation layered over calculated data.

**Observed result:** A 382-line report was generated and CodeRAG was shown as
`SKIP`. Generation was automatic and the report was manually inspected. The line
count is not a stability guarantee.

**Assessment and open questions:** Useful for review and handoff, but timestamps,
ordering, and external results limit raw diff stability. Open questions are stable
section IDs, report-diff semantics, and clearer fact-versus-recommendation labels.

**Representative task and severity:** A reviewer should start from the report status,
open the relevant raw artifact, and identify one follow-up inspection. Mislabeling a
failed artifact as `OK` is **blocking**; unstable ordering is a **version-control
convenience** issue.

**Improvement suggestion (report correctness and reproducibility):** Define stable
finding IDs from finding type, qualified name, source path, and normalized identity,
never row position. Sort sections and findings deterministically, emit a compact
machine-readable summary, and only then add report-diff support.

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

**Intended user and decision:** Developer or LLM agent; form a focused architectural
hypothesis. Optional and exploratory, not a CI gate or automated move authority.

**Success/failure:** Success means results respect the requested query, label, and
scope and include query metadata. Failure means CBM is unavailable, the query
fails, or results escape scope. In this evaluation structural scope worked, but
semantic rows still included `.eval` paths.

**Observed result:** 157 total matches and 20 rows were returned. Output was
automatically produced as terminal JSON and manually inspected; counts are one-run
observations. The command is read-only and writes no artifact unless redirected.

**Assessment and open questions:** Useful for interactive discovery, but semantic
results are not yet trustworthy for automated refactoring. Open questions are
pre-ranking exclusion enforcement and stable saved-search metadata across CBM
versions.

**Representative task and severity:** An LLM agent should locate the dependency
analysis functions with the documented query and then verify the returned paths
against the source tree. `.eval` leakage is **blocking for automation** but
**acceptable for manual exploration** when results are inspected.

**Improvement suggestion (blocking correctness before convenience):** Apply path and
qualified-name exclusions before ranking and define zero-result behavior explicitly
as a successful empty result. Saved output and metadata are follow-ups; when added,
record query parameters, scope, provider/version, configuration hash, discarded-row
counts, and the filtering stage.

### Evaluation conclusion and next order

The most valuable immediate refinement is corpus isolation because it affects both
Phase A semantic retrieval and focused search. After that, add quality baselines,
feature-level artifact tests, optional CodeRAG evaluation, stronger native metrics,
and continued extraction of the remaining CLI/config/workflow code from
`__init__.py`. Each refinement should repeat the six chapters from a clean output
directory and compare the generated artifacts with the previous baseline.

### Cross-cutting acceptance work

Before treating any feature as automation-safe, add automated acceptance tests for
the documented success and negative-path criteria: invalid configuration, syntax
errors, missing CBM, malformed candidate artifacts, empty search results,
include/exclude collisions, and partial indexing. The tests must record command
exit codes, validate generated artifact schemas and required fields, check scope
exclusions, and verify report/source-link consistency. This is evaluation
infrastructure, not another feature-specific convenience suggestion.

### Refinement priority

1. Automated success and negative-path tests, including exit codes and artifact schemas.
2. Phase A corpus isolation and semantic-result filtering.
3. Tree schema validation and deterministic output.
4. Native quality-report baseline comparison and regression status.
5. Search provenance plus stable report/finding identifiers.
6. Additional complexity and maintainability metrics.

The first two items are blocking correctness work for automated refactoring. Tree
and baseline work is required for trustworthy repeated evaluations. Stable IDs,
saved search metadata, and additional metrics improve reproducibility and
convenience but should not delay the correctness fixes.

## Working Rules

- change one cohesive slice at a time
- validate immediately after each slice
- avoid behavior changes while extracting structure
- do not introduce generic catch-all utility modules