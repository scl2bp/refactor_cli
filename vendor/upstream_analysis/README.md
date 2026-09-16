# Vendored Upstream Analysis Tools

These files are preserved for comparison and selective reuse while the
capabilities are consolidated into `refactor_cli.analysis`.

Sources retrieved on 2026-09-16:

- `analyze_internal_dependencies.ps1` and `internal_module_dependencies.py` from `Scherlac/JapaneseLessons`, branch `feature/lesson-database`
- `quality_gate_report.py`, `find_unused.py`, and `find_duplicates.py` from `Scherlac/felvi_games`, branch `main`

The vendored scripts are reference material for the production adapters, not
part of the production CLI scan scope. The supported interfaces are:

- `refactor-cli internal-dependencies-report` for module graph analysis
- `refactor-cli quality-gate` for complexity and baseline regression checks

`refactor-cli quality-report` is retained as a compatibility alias for the
complexity gate.