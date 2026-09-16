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
- `candidate-phase-a`
- `candidate-report`
- `candidate-search`

`candidate-report` now defaults to an architecture-first summary. Demo-style semantic
example sections are omitted unless `--include-demo-artifacts` is passed.

`candidate-search` is a thin wrapper around `codebase-memory-mcp cli search_graph`
that auto-fills project defaults from `.refactor/config.json` (`candidate_analysis`
section): project name, CBM binary, scope path, semantic terms, and limit.

If you run it from inside a project directory, the command will look for `.refactor/config.json`
in the current folder or any parent folder automatically.

## Code Analysis and Quality Features

### Chapter 1: Configured file discovery

**Feature description:** `files` resolves the project root and lists the Python
files selected by `.refactor/config.json`. It is the input boundary for all later
structural and quality analysis.

**Command and options:**

```bash
refactor-cli files --config .refactor/config.json
```

The `--config` option may point to another project configuration. The command
prints the resolved project root and discovered files.

**Generated files:** None. This is a read-only discovery command.

**Generated-file description:** Since no file is written, the terminal output is
the evaluation result. It should show the intended project root and exclude
`.venv`, caches, build output, and other configured exclusions.

**Usefulness evaluation:** Essential and reliable as the first step. The current
configuration discovered 18 Python files, matching the source tree used by the
subsequent evaluations.

**Improvement suggestion:** Add machine-readable output, such as `--format json`,
and report included and excluded counts so later commands can consume the exact
same discovery result.

### Chapter 2: Structural tree analysis

**Feature description:**

`tree` discovers the configured Python files and records their top-level structure
in `.refactor/tree.yaml`. The tree includes modules, functions, classes, constants,
and other top-level nodes. It is the planning and verification boundary for
structural refactoring.

**Command and options:**

```bash
refactor-cli tree --config .refactor/config.json --output .refactor/tree.yaml --print
```

**Generated files:** `.refactor/tree.yaml`.

**Generated-file description:** A compact YAML inventory containing each discovered
file and its top-level LibCST nodes. `--print` also displays the tree in the
terminal.

**Usefulness evaluation:** High. It provides a persistent, reviewable target for
planning moves and verifying that a structural edit produced the requested result.
The clean evaluation regenerated a tree for all 18 files.

**Improvement suggestion:** Add explicit schema/version validation and a JSON
summary of node counts per file so large trees can be compared without parsing YAML.

### Chapter 3: Native quality report

`quality-report` performs a local AST-based analysis without requiring CBM. It
reports:

- module import dependencies, fan-in, and fan-out
- dependency cycles and short dependency paths
- Mermaid dependency diagrams and source-file links
- function complexity hotspots
- normalized AST duplicate groups
- unused public top-level functions
- high fan-out modules as move candidates

It writes `quality.json` and `quality.md` to the selected output directory. The
default is `.refactor/analysis/quality/`. The report is a refactoring signal, not a
replacement for tests, coverage, or a full static type checker. Complexity is a
small AST heuristic, and unused-function detection is intentionally conservative.

**Command and options:**

```bash
refactor-cli quality-report \
  --config .refactor/config.json \
  --scope-path src/refactor_cli \
  --output-dir .refactor/analysis/quality
```

**Generated files:** `.refactor/analysis/quality/quality.json` and
`.refactor/analysis/quality/quality.md`.

**Generated-file description:** The JSON contains module rows, dependency paths,
cycles, complexity records, duplicate groups, unused functions, and move
candidates. The Markdown file renders those findings with tables, source links,
and a Mermaid diagram.

**Usefulness evaluation:** High for local refactoring triage and independent of
CBM. The clean evaluation found 18 modules, no parse errors, 7 move candidates,
0 duplicate groups, and 66 unused public-function findings. These are signals,
not quality gates.

**Improvement suggestion:** Add baseline comparison, cyclomatic/maintainability
metrics, and explicit regression status so the report can detect whether a move
improved the code rather than only ranking current hotspots.

### Chapter 4: Candidate analysis pipeline

`candidate-phase-a` runs configured adapters over Codebase Memory tooling and writes:

- `source_index.json`: indexed files, node/edge counts, exclusions, and parse health
- `dependency_graph.json`: scoped `CALLS`, `IMPORTS`, and `INHERITS` rows
- `semantic_retrieval.json`: grouped structural matches and semantic search results
- `architecture_report.json`: hotspots, clusters, entry points, node labels, and edge types
- `summary.json`: status for each pipeline module
- `coderag_validate.json`: optional CodeRAG validation when enabled

The default directory is `.refactor/analysis/candidates/`. `candidate-report`
renders these artifacts into `report.md`, including status, artifact sizes, Mermaid
diagrams, input/output interpretation, readiness, and index-health sections.

`candidate-search` is the focused interactive form of the same discovery capability.
It accepts semantic terms, labels, scopes, limits, and additional CBM graph flags.
Use it to investigate a specific architectural question without rebuilding the full
Phase A artifact set.

**Command and options:**

```bash
refactor-cli candidate-phase-a --config .refactor/config.json
```

The configuration supplies the project name, CBM binary, index mode, scope path,
qualified-name prefix, semantic terms, result limit, and exclusions. CLI options
override configuration when supplied. `--include-coderag-validate` enables the
optional CodeRAG validation step.

**Generated files:** `.refactor/analysis/candidates/source_index.json`,
`dependency_graph.json`, `semantic_retrieval.json`, `architecture_report.json`,
and `summary.json`; optionally `coderag_validate.json`.

**Generated-file description:** The source index records indexing coverage and
parse health. The dependency graph stores scoped relationship rows. Semantic
retrieval stores grouped structural and ranked semantic hits. The architecture
report summarizes hotspots and clusters. The summary records `OK`, `FAIL`, or
`SKIP` for each adapter.

**Usefulness evaluation:** High when CBM is available: all four enabled adapters
completed `OK` in the clean evaluation. It provides richer call, inheritance, and
semantic information than the native AST report. However, the index contained
45,392 nodes and 194,841 edges, with 60 partial parses, so its scope and health
must be checked before trusting recommendations.

**Improvement suggestion:** Enforce source-scope isolation at indexing time and
report discarded paths. The current semantic corpus can still expose `.eval`
entries even when qualified-name exclusions are configured.

### Chapter 5: Candidate report

The following commands evaluate the complete analysis surface from the repository
root. The configured scope is `src/refactor_cli`.

**Feature description:** `candidate-report` converts the Phase A JSON artifacts
into a readable architecture and readiness report.

**Command and options:**

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

The report accepts the configured input directory and output path through the
candidate-analysis settings; use `--input-dir` and `--output` to override them.

**Generated files:** `.refactor/analysis/candidates/report.md`.

**Generated-file description:** Markdown containing pipeline status, artifact sizes,
raw-file interpretation, Mermaid status and relationship diagrams, readiness, index
health, and architecture findings.

**Usefulness evaluation:** High for human review and handoff. The clean run
generated a 382-line report and made the raw JSON artifacts considerably easier to
compare. It correctly showed CodeRAG as `SKIP` because it was disabled.

**Improvement suggestion:** Add stable section identifiers and a compact machine
summary of finding counts, then add a report-diff mode for comparing two runs.

### Chapter 6: Focused candidate search

**Feature description:** `candidate-search` runs a focused CBM graph/semantic
query without rebuilding the full Phase A artifact set.

**Command and options:**

```bash
refactor-cli candidate-search \
  --config .refactor/config.json \
  --semantic-query 'dependency,module,quality metrics' \
  --label Function \
  --limit 20
```

Useful options include `--profile`, `--scope-path`, `--scope-qn-prefix`,
`--file-pattern`, `--format json|tree`, and `--cbm-options` for additional graph
flags such as `--relationship CALLS`.

**Generated files:** None by default. Results are printed as JSON to the terminal.

**Generated-file description:** The terminal result contains grouped structural
matches and semantic rows, including labels, source files, scores, and graph degree
information. Redirect it explicitly if a saved artifact is needed.

**Usefulness evaluation:** High for interactive investigation. The clean run
returned 157 total matches and 20 rows. It is fast for targeted questions, but
semantic results included `.eval` paths, so the output is not yet clean enough to
drive an automated move decision.

**Improvement suggestion:** Apply configured path and qualified-name exclusions to
semantic rows before printing, and add `--output` plus a query metadata envelope
for reproducible saved searches.

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
  },
  "candidate_analysis": {
    "project_name": null,
    "cbm_binary": null,
    "index_mode": "moderate",
    "max_rows": 5000,
    "semantic_terms": ["dependency", "module", "call graph"],
    "semantic_limit": 100,
    "scope_path": "src/app",
    "scope_qn_prefix": "app",
    "exclude_qn_substrings": [".eval."],
    "include_coderag_validate": false,
    "coderag_path": ".eval/candidates/coderag",
    "output_dir": ".refactor/analysis/candidates",
    "report_output": ".refactor/analysis/candidates/report.md",
    "include_demo_artifacts": false,
    "semantic_query_profiles": [
      {
        "name": "Input processing",
        "query": "config parse validation",
        "why": "Locate where inputs are loaded and normalized",
        "scope_path": "src/app"
      },
      {
        "name": "Calculation",
        "query": "algorithm compute simulation",
        "why": "Locate core processing paths",
        "scope_path": "src/app"
      },
      {
        "name": "Reporting",
        "query": "report export dashboard",
        "why": "Locate user-facing output generation",
        "scope_path": "src/app"
      }
    ]
  }
}
```

The `candidate_analysis` section is optional, but once present it becomes the default
source for `candidate-phase-a` and `candidate-report`. CLI flags override config only
when explicitly passed.

`semantic_query_profiles` lets each project define domain-relevant semantic intents.
These profiles are summarized in the default report, while detailed demo-style query
walkthroughs remain opt-in via `--include-demo-artifacts`.

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

## Candidate Search Wrapper

Use this command when you want CBM search results without manually rebuilding the full
`search_graph` command each time.

Run with a configured semantic profile:

```bash
refactor-cli candidate-search --profile "Calculation and processing" --label Class
```

Run with explicit semantic terms (overrides profile/config defaults):

```bash
refactor-cli candidate-search \
  --semantic-query '["simulation","run_model","throughput","servicegrad","kanban"]' \
  --label Class
```

Override only the scope while keeping all other defaults:

```bash
refactor-cli candidate-search --scope-path crin4_sim --label Function
```

Pass additional raw CBM flags through to `search_graph`:

```bash
refactor-cli candidate-search \
  --profile "Calculation and processing" \
  --cbm-options "--min-degree 2 --include-connected --relationship CALLS"
```

Notes:

- The wrapper uses direct subprocess argument passing, so wildcard scope patterns do not
  get expanded by the shell.
- `--semantic-query` accepts either a JSON array string or a comma-separated list.
- `--cbm-options` expects a simple `--flag value --flag2 value2` tail; flags without
  values are treated as booleans.

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
refactor-cli candidate-phase-a
refactor-cli candidate-report
refactor-cli candidate-report --include-demo-artifacts
```

If `.refactor/config.json` contains `candidate_analysis` defaults, those two commands
can usually run without additional parameters from the target repository root.

## Candidate-Based Phase A Modules

The `candidate-phase-a` command runs thin adapters over installed candidate tools
instead of custom reimplementation.

Current module outputs:

- `source_index.json`
- `dependency_graph.json`
- `semantic_retrieval.json`
- `architecture_report.json`
- `summary.json`

Optional:

- `coderag_validate.json` (when `--include-coderag-validate` is set)

Default output directory:

- `.refactor/analysis/candidates/`

Scope and noise controls (recommended defaults):

- `--scope-path src/refactor_cli`
- `--scope-qn-prefix refactor_cli.src.refactor_cli`
- `--exclude-qn-substring .eval.`

Operational policy for this repository:

- Persistent daemon mode is intentionally out-of-scope.

### Readable Report Output

To render the raw candidate JSON artifacts as a readable Markdown report with
Mermaid diagrams:

```bash
refactor-cli candidate-report
```

Default output:

- `.refactor/analysis/candidates/report.md`

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