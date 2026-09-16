# Refactoring Plan

## Goals

This refactoring follows the SWE guidance in [docs/swe.md](docs/swe.md):

- high cohesion: each module should own one responsibility
- low coupling: workflow layers should depend on lower-level services, not the reverse
- composition over branching: move backends and safeguards should be composed into the workflow

The current implementation in `src/refactor_cli/__init__.py` mixes package entrypoint, CLI, tree serialization, CST analysis, workflow orchestration, and runtime tool execution. The path below separates those concerns incrementally while preserving behavior after each phase.

The current reports confirm that the extraction has started, but the package still
has a central coordinator and a CLI dependency cycle. The remaining work should
prioritize clear boundaries and trustworthy evidence over adding more analysis
features.

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
- `src/refactor_cli/analysis/quality_gate.py`
  - baseline-aware complexity, lint, duplication, and coverage gate adapter
- `src/refactor_cli/analysis/internal_dependencies_report.py`
  - compatibility surface for the provider-independent module graph report

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
3. Tree file count, internal-dependency-report file count, and source-index staged-file count
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
inventory used for planning and verification. `internal-dependencies-report` performs local,
provider-independent analysis over that scope. `candidate-phase-a` adds external
index, dependency, semantic, and architecture signals. `candidate-report` presents
those Phase A artifacts; `candidate-search` is an interactive follow-up query.

The configured file set is the analysis corpus. Repository files outside that set
are not additional analysis input. They are relevant only when a configured file
imports, includes, re-exports, or otherwise references them; those references are
reported as external dependencies. This keeps unrelated `.eval`, vendor, cache,
documentation, and generated files out of the evidence. Expanding the analysis
boundary is a configuration change and must be recorded in run provenance.

The AST baseline is authoritative for facts derived from the configured files. The
native quality report and Phase A CBM outputs must be compared against that same
baseline before a finding can support automated refactoring. No feature currently
provides enough evidence to authorize an automated refactoring move without human
review.

### Chapter 0: Configured-scope AST baseline

**Feature description:** `candidate-phase-a` emits a deterministic,
provider-independent AST baseline over exactly the files resolved from
`python_files.include` and `python_files.exclude`.

**Generated file:** `.refactor/analysis/candidates/scope_baseline.json`.

**Generated-file description:** The artifact records configured files, parsed files,
parse errors, internal `IMPORTS` edges between configured modules, and imports that
leave the configured corpus. External imports are context, not additional evidence
that expands the analysis scope.

**Authority and acceptance:** The configured-file count must agree with `files`;
every configured file must appear in either `parsed_files` or `parse_errors`; and
internal edges must have both endpoints in the configured module set. Syntax or
decode failures are visible baseline defects, not successful partial analysis.

**Current status:** Implemented as the first scope-isolation slice. It establishes
the factual comparison surface for CBM outputs; it does not yet adjudicate AST/CBM
disagreements or authorize moves.

**Next refinement:** Compare CBM rows with this baseline and report missing, extra,
and scope-crossing relationships before any candidate is marked reviewable for
automation.

### Cross-validation result

The current isolated comparison normalizes CBM symbol-level `IMPORTS` rows to module
edges and compares them with the AST baseline. It matched 45 of 47 AST internal
import edges, found 46 CBM module edges, and found one extra CBM edge. The two
missing and one extra edges remain visible in the candidate report and keep the
overall decision below automation-ready. This is evidence that the two analyzers
are close but not interchangeable; disagreement must be explained per edge before
an automated move can rely on the relationship graph.

### Machine-readable evaluation

`candidate-evaluate` is the acceptance layer for generated Phase A artifacts:

```bash
refactor-cli candidate-evaluate --config .refactor/config.json
```

It writes `evaluation.json` with stable Boolean checks, scope and index counts,
semantic locality counts, AST/CBM import comparison details, and an explicit
`ready_for_automation` decision. A complete but degraded analysis exits successfully
with status `DEGRADED`; missing required artifacts produce `FAIL` and a non-zero exit
code. Semantic acceptance uses the same scope-accounting helper as the Markdown
report, including discarded rows, so filtered contamination cannot pass merely
because the remaining rows are local.

The Markdown report remains the human presentation. It may contain richer narrative,
examples, and diagrams, but `evaluation.json` is the machine contract used by CI or
an automation controller.

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

**Observed result:** 23 Python files were discovered. This is reproducible with the
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

**Generated-file description:** Compact YAML containing 23 files and their modules,
functions, classes, constants, and other top-level nodes.

**Intended user and decision:** Developer or LLM agent; decide which symbols can be
moved and whether an applied edit matches the requested structure. Required for the
tree-edit workflow; optional for standalone quality analysis.

**Success/failure:** Success means configured files and relevant top-level nodes are
represented and post-apply verification matches the requested tree. Failure means a
parse error, missing/misclassified node, or failed tree comparison. The compact tree
intentionally omits a full AST, call graph, type model, local nested symbols, and
runtime behavior.

**Observed result:** The run generated a 23-file tree. It was manually inspected
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

### Chapter 3: Internal dependency report

**Feature description:** `internal-dependencies-report` performs local AST analysis without CBM.
It calculates imports, fan-in/fan-out, cycles, dependency paths, complexity,
normalized duplicate groups, unused public functions, and high-fan-out move
candidates.

**Command and options:**

```bash
refactor-cli internal-dependencies-report \
  --scope-path src/refactor_cli \
  --output-dir .refactor/analysis/quality
```

**Generated files:** `.refactor/analysis/quality/internal_module_dependencies.json`
and `.refactor/analysis/quality/internal_module_dependencies.md`.

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

**Observed result:** 23 modules, no parse errors, 8 move candidates, 0 duplicate
groups, and 71 unused-function findings. These are heuristic, one-run observations,
not removal instructions; public APIs, CLI handlers, callbacks, and dynamic
registration can be reported as unused.

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

- `.refactor/analysis/candidates/scope_baseline.json`
- `.refactor/analysis/candidates/source_index.json`
- `.refactor/analysis/candidates/dependency_graph.json`
- `.refactor/analysis/candidates/semantic_retrieval.json`
- `.refactor/analysis/candidates/architecture_report.json`
- `.refactor/analysis/candidates/summary.json`
- optional `.refactor/analysis/candidates/coderag_validate.json`

**Generated-file description:** The AST scope baseline records the exact configured
file set, parse health, internal imports, and external imports. The source index
records CBM coverage and parse health;
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

**Observed result:** The configured corpus contained 23 files. The AST baseline
parsed all 23 files, found 47 internal import edges and 79 external imports. The
isolated CBM corpus contained 250 nodes and 1,189 edges with zero partial parses
and zero unindexed files. Artifacts were automatically produced and manually
reviewed.

**Assessment and open questions:** The corpus boundary is now aligned with the
configured files, making CBM useful for comparison with AST facts. It is still not
safe for automated moves until AST/CBM agreement and dynamic Python risks are
checked. Open questions are how relationship disagreements should be classified.

**Representative task and severity:** A developer should use the architecture report
to locate the central coordination modules and then inspect dependency edges. Broad
index contamination is **blocking for automation** but **acceptable for manual
exploration** when the source index health is reviewed.

**Improvement suggestion (next technical fix):** Compare CBM relationships with the
AST baseline, report missing and extra edges, and block automation on unexplained
disagreements. Keep post-query scope filtering as a safety net and add an acceptance
test proving that `.eval` and vendored paths cannot enter the configured corpus.

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

**Observed result:** A 490-line report was generated and CodeRAG was shown as
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

### Chapter 7: Complexity and quality gate

**Feature description:** `quality-gate` runs provider-independent static quality
analysis over the configured source paths and compares the current snapshot with a
stored baseline. It is a regression gate, not an absolute code-quality score and
not an authorization for automated refactoring.

**Command and options:**

```bash
refactor-cli quality-gate --refresh-baseline --no-cache
refactor-cli quality-gate --fail-on-gate --no-cache
```

The default output directory is `.refactor/analysis/gate`. `--refresh-baseline`
writes a new baseline; `--fail-on-gate` maps `FAIL` and `NO_BASELINE` to a non-zero
exit code; `--no-coverage` intentionally omits coverage; and `--no-cache` forces a
fresh coverage test run instead of reusing recent coverage data. `--scope-path`,
`--paths`, and `--output-dir` override the configured analysis boundary and output.

**Generated files:**

- `.refactor/analysis/gate/complexity_baseline.json`
- `.refactor/analysis/gate/complexity_current.json`
- `.refactor/analysis/gate/complexity_report.md`
- `.refactor/analysis/gate/coverage_current.json` when coverage is enabled

#### Gate subfeatures

1. **Cyclomatic complexity:** Radon calculates block complexity, A-F ranks, average
  complexity, p95 complexity, D-or-worse blocks, F blocks, and top complex blocks.
  The gate thresholds regressions in average, p95, rank counts, block complexity,
  and significant block changes.
2. **Maintainability and source size:** the snapshot records maintainability index,
  LOC, SLOC, and blank lines. These are diagnostic metrics in the current gate;
  they do not independently fail it.
3. **Coverage:** the configured test command runs `pytest-cov` against
  `src/refactor_cli`, writes JSON coverage, and compares total coverage against
  the baseline. Coverage can enforce a minimum and maximum allowed drop. A fresh
  run disables pytest's cache provider and erases old coverage data before tests.
4. **Lint regression:** Ruff findings and category counts are recorded and the
  increase from baseline is gated, while existing findings remain visible as
  technical debt.
5. **Duplication:** normalized AST function bodies are compared and duplicate
  block-pair counts are baseline-gated. This is a structural heuristic, not
  semantic clone detection.
6. **Cohesion and interface metrics:** class LCOM, average parameters, high-parameter
  functions, and untyped public functions are reported. High-parameter counts are
  baseline-gated; LCOM and untyped counts are currently diagnostic.
7. **Unused-function analysis:** top-level unused functions are reported and their
  count is baseline-gated. Dynamic exports, callbacks, plugins, reflection, and
  CLI registration can produce false positives, so findings require review.
8. **Baseline decision and exit contract:** the report emits `PASS`, `FAIL`, or
  `NO_BASELINE`, explains the reasons, records metric deltas and thresholds, and
  preserves the current snapshot even when the gate fails.

**Authority and acceptance:** The AST/static snapshot is authoritative for the
configured files and static metrics. Coverage is authoritative only when the report
says `Coverage status: OK` and `Coverage source: fresh test run` (or an explicitly
accepted recent cache source). A successful command without a baseline is not a
passing regression check. CI should use `--fail-on-gate --no-cache` and inspect the
report, not only the process exit code.

**Observed result:** The current 23-file baseline contains 5,143 LOC, average
complexity 5.299, p95 complexity 15, three D-or-worse blocks, one F block, 35 Ruff
findings, three duplicate pairs, four high-parameter functions, six unused
top-level functions, and 39.99% fresh coverage across 16 measured files. The
strict comparison passed with zero deltas. The F-ranked block is
`build_candidate_report`; it is a refactoring candidate, not a failure by itself.

**Evaluation protocol:** For every gate evaluation, record repository path and
commit, working-tree status, Python/package versions, configuration hash, scope
paths, baseline timestamp, exact command, cache mode, coverage source, exit code,
and artifact paths. Validate that:

1. every expected JSON and Markdown artifact exists and parses;
2. the snapshot paths match the intended configured scope;
3. coverage is not reported as successful when the test command or coverage import
  failed;
4. baseline and current snapshots have the same schema and comparable metric keys;
5. `--fail-on-gate` returns non-zero for both missing baselines and failed gates;
6. `--refresh-baseline` is used deliberately and is not treated as a regression
  check; and
7. a `--no-cache` run reports a fresh test source and does not reuse `.coverage`.

**Assessment:** Useful and repeatable as a regression guard. It is currently not a
release-quality threshold because coverage is 39.99%, Ruff reports 35 existing
findings, and one F-ranked block remains. The gate's strongest value is preventing
new regressions while behavior coverage and architecture boundaries improve.

**Improvement suggestion:** Keep the metric families separate in the report and
raise thresholds incrementally only after focused tests cover transforms,
safeguards, discovery, and tree handling. Add provenance fields and schema
validation before adding more metrics. Do not turn heuristic unused-function or
complexity findings into automatic deletion or movement decisions.

## Current Project Assessment

The project is structurally healthy enough for continued manual refactoring:
all 23 configured files parse, all configured files are indexed, and the quality
gate passes against its refreshed baseline. It is not yet safe for automated moves.
The candidate evaluation is `DEGRADED`, with 45/47 AST/CBM import edges agreeing
and 94/100 semantic rows local to the configured scope. The three unexplained
import differences and six non-local semantic rows must remain visible as
uncertainty, not be converted into refactoring actions.

The complexity gate is a regression gate, not an absolute quality grade. The
current snapshot has average cyclomatic complexity 5.299, one F-ranked block,
three D-or-worse blocks, 35 Ruff findings, three duplicate pairs, six unused
top-level functions in the gate's narrower heuristic, and 39.99% fresh coverage.
The separate dependency report finds 71 unused functions; this disagreement is
expected from different heuristics and means neither count should drive automated
deletion.

### Highest-value Technical Debt

1. **Central coordination and dependency cycle.** `__init__.py` remains the package
  entrypoint, public API, and home for command/workflow logic. `cli.commands` has
  fan-out 15, and the dependency report shows a cycle through `refactor_cli` and
  `cli.parser`. Complete the thin CLI shell and make the package entrypoint export
  stable functions only. This is the primary cohesion and coupling issue.
2. **Untyped workflow boundaries.** Commands pass `argparse.Namespace` and loosely
  shaped dictionaries between configuration, analysis, and report layers. Add
  small typed models for resolved project settings, analysis artifacts, and gate
  results before adding more adapters. This reduces hidden contracts without
  introducing a general framework.
3. **Insufficient behavioral coverage for refactoring operations.** Fresh coverage
  is 39.99%, with particularly low coverage in `transforms.py`, `safeguards.py`,
  `discovery.py`, and `tree_codec.py`. Add focused tests for move application,
  rollback/safeguards, malformed trees, and CLI exit codes. Raise the coverage
  threshold only after those behavior tests exist; do not treat coverage alone as
  proof of correctness.
4. **Analysis-provider disagreement.** Keep AST as the authority for configured
  scope and module imports. Filter semantic rows before ranking and classify the
  two missing plus one extra CBM import edge. Automated refactoring should remain
  blocked while these differences are unexplained.

### Deliberately Deferred

- Do not remove the 71 unused-function findings automatically; validate exports,
  callbacks, plugin entry points, and CLI registration first.
- Do not optimize the one F-ranked `build_candidate_report` block before adding
  characterization tests; it is a maintainability target, not evidence of a bug.
- Do not add CodeRAG or more metrics until the package boundary, test coverage, and
  report provenance are stable.

### Recommended Next Order

1. Extract parser/handlers and remaining transition orchestration from `__init__.py`;
  remove the `refactor_cli` <-> `cli` cycle.
2. Introduce narrow typed models at config, command-result, and artifact boundaries.
3. Add focused behavior and negative-path tests, then retain the fresh coverage
  gate with `--no-cache` in CI.
4. Finish AST/CBM disagreement classification and pre-ranking semantic filtering.
5. Only then consider further complexity decomposition and stricter thresholds.

### Cross-cutting acceptance work

Before treating any feature as automation-safe, add automated acceptance tests for
the documented success and negative-path criteria: invalid configuration, syntax
errors, missing CBM, malformed candidate artifacts, empty search results,
include/exclude collisions, and partial indexing. The tests must record command
exit codes, validate generated artifact schemas and required fields, check scope
exclusions, and verify report/source-link consistency. This is evaluation
infrastructure, not another feature-specific convenience suggestion.

### Refinement priority

1. Extract the remaining CLI/workflow coordinator and remove the module cycle.
2. Introduce typed models for configuration and artifact contracts.
3. Add automated success and negative-path tests, including exit codes and schemas.
4. Complete AST/CBM cross-validation and pre-ranking semantic filtering.
5. Validate tree schema and deterministic report/finding identifiers.
6. Tighten quality thresholds only after behavior coverage improves.

The first two items are blocking correctness work for automated refactoring. Tree
and baseline work is required for trustworthy repeated evaluations. Stable IDs,
saved search metadata, and additional metrics improve reproducibility and
convenience but should not delay the correctness fixes.

## Working Rules

- change one cohesive slice at a time
- validate immediately after each slice
- avoid behavior changes while extracting structure
- do not introduce generic catch-all utility modules