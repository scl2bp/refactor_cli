# Code Quality Gate Report

Generated at (UTC): 2026-09-16T19:19:50+00:00
Scope: src/refactor_cli

## Gate

QUALITY_GATE: PASS

Reasons:
- No significant regression vs baseline.

## Current Snapshot

- Python files: 23
- LOC: 5120 (SLOC: 4318, Blank: 717)
- Avg MI: 53.686
- Avg CC: 5.293
- P95 CC: 15.0
- Rank counts: A=120, B=35, C=16, D=2, E=0, F=1
- D/E/F blocks: 3
- F blocks: 1
- Parse-error files: 0
- Unused top-level functions: 6
- Coverage: N/A%

## Coverage

- Total line coverage: N/A%
- Files measured: 0
- Coverage status: OK

## Code Repetition

- Structural duplicate function pairs: 3

| Clones | Body Size | Location A | Location B |
|---:|---:|---|---|
| 2 | 103 | src/refactor_cli/candidate_report.py:282 _profile_terms | src/refactor_cli/__init__.py:256 _profile_terms_setting |
| 2 | 64 | src/refactor_cli/candidate_report.py:583 _scoped_module_dependency_edges | src/refactor_cli/candidate_report.py:618 _scoped_class_inheritance_edges |
| 2 | 56 | src/refactor_cli/candidate_report.py:566 _scoped_dependency_edges | src/refactor_cli/candidate_report.py:601 _scoped_class_method_edges |


## Cohesion

- Classes analyzed: 1
- Avg LCOM1: 1.0 (0=cohesive, 1=disconnected)

### Low-Cohesion Classes (LCOM1 > 0.7)

| LCOM1 | Class | File |
|---:|---|---|
| 1.0 | Normalize | src/refactor_cli/analysis/quality_report.py:77 |


## Interface Complexity

- Public functions analyzed: 78
- Avg parameters: 1.885
- High-parameter functions (> 5 params): 4
- Untyped public functions (no return annotation): 0

### High-Parameter Functions

| Params | Function | File |
|---:|---|---|
| 7 | build_candidate_report | src/refactor_cli/candidate_report.py:1065 |
| 6 | run_tree_transition | src/refactor_cli/transforms.py:449 |
| 6 | collect_dependency_graph | src/refactor_cli/analysis/dependency_graph.py:15 |
| 6 | collect_semantic_retrieval | src/refactor_cli/analysis/semantic_retrieval.py:7 |


## Unused Functions

- Unused top-level functions: 6
- Unused analysis status: OK

| Symbol | File |
|---|---|
| write_yaml | src/refactor_cli/file_io.py:27 |
| yaml_text | src/refactor_cli/file_io.py:33 |
| _structural_profile_payload | src/refactor_cli/candidate_report.py:511 |
| _fallback_dependency_rows | src/refactor_cli/candidate_report.py:678 |
| _markdown_profile_table | src/refactor_cli/candidate_report.py:1023 |
| choose_operation | src/refactor_cli/__init__.py:347 |

## Ruff Lint

- Total violations: 35
- By category: B=1, D=2, F=12, I=10, P=7, R=2, S=1
- Ruff status: OK

## Baseline Delta

- Baseline timestamp: 2026-09-16T19:19:49+00:00
- Delta avg_cc: 0.0
- Delta p95_cc: 0.0
- Delta D/E/F blocks: 0
- Delta F blocks: 0
- Delta parse-error files: 0
- Delta ruff_violations: 0
- Delta duplicate_block_pairs: 0
- Delta high_param_count: 0
- Delta unused_function_count: 0


## Gate Thresholds

- max_avg_cc_increase: 0.35
- max_p95_cc_increase: 1.25
- max_d_or_worse_increase: 3
- max_f_increase: 0
- max_block_cc_increase: 4.0
- max_significant_block_regressions: 1
- min-coverage-pct: 0.0
- max-coverage-drop: 1.0
- max_ruff_violations_increase: 5
- max_duplicate_pairs_increase: 2
- max_high_param_increase: 2
- max_unused_function_increase: 0

## Top Complex Blocks

| Rank | CC | Location |
|---|---:|---|
| F | 63.0 | src/refactor_cli/candidate_report.py:1065 build_candidate_report |
| D | 26.0 | src/refactor_cli/candidate_report.py:435 _semantic_profile_payload |
| D | 25.0 | src/refactor_cli/transforms.py:449 run_tree_transition |
| C | 20.0 | src/refactor_cli/analysis/scope_baseline.py:42 collect_scope_baseline |
| C | 20.0 | src/refactor_cli/analysis/quality_report.py:120 collect_quality_report |
| C | 17.0 | src/refactor_cli/transforms.py:75 apply_unified_diff_to_text |
| C | 17.0 | src/refactor_cli/candidate_report.py:678 _fallback_dependency_rows |
| C | 17.0 | src/refactor_cli/analysis/quality_report.py:94 _unused_functions |
| C | 17.0 | src/refactor_cli/analysis/quality_report.py:221 render_quality_report |
| C | 15.0 | src/refactor_cli/transforms.py:44 build_updated_source |
| C | 15.0 | src/refactor_cli/candidate_report.py:729 _search_hit_dependency_rows |
| C | 14.0 | src/refactor_cli/__init__.py:266 _resolve_candidate_search_settings |
| C | 14.0 | src/refactor_cli/analysis/quality_report.py:45 _imports |
| C | 13.0 | src/refactor_cli/__init__.py:510 cmd_apply_tree_patch |
| C | 13.0 | src/refactor_cli/__init__.py:590 cmd_apply_tree_edit |

## Copilot Summary

- Quality gate passed: no significant complexity or coverage regression detected.
