import argparse
from refactor_cli.cli.commands import (
    cmd_candidate_phase_a,
    cmd_candidate_report,
    cmd_candidate_evaluate,
    cmd_candidate_search,
    cmd_quality_report,
    cmd_internal_dependencies_report,
    cmd_quality_gate,
)
from refactor_cli import DEFAULT_CONFIG
from refactor_cli import cmd_init
from refactor_cli import cmd_files
from refactor_cli import DEFAULT_TREE
from refactor_cli import cmd_tree
from refactor_cli import cmd_format
from refactor_cli import DEFAULT_TREE_PATCH
from refactor_cli import DEFAULT_APPLIED_PATCHES_DIR
from refactor_cli import cmd_apply_tree_patch
from refactor_cli import DEFAULT_TREE_EDIT
from refactor_cli import cmd_apply_tree_edit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project-agnostic structural refactoring tool"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="Create default .refactor/config.json"
    )
    init_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=cmd_init)

    files_parser = subparsers.add_parser(
        "files", help="List relevant Python files from config"
    )
    files_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    files_parser.set_defaults(func=cmd_files)

    tree_parser = subparsers.add_parser(
        "tree", help="Generate and persist project structural tree"
    )
    tree_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    tree_parser.add_argument("--output", default=str(DEFAULT_TREE))
    tree_parser.add_argument("--print", action="store_true")
    tree_parser.set_defaults(func=cmd_tree)

    format_parser = subparsers.add_parser(
        "format", help="Format all discovered Python files using ruff"
    )
    format_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    format_parser.set_defaults(func=cmd_format)

    apply_tree_patch_parser = subparsers.add_parser(
        "apply-tree-patch",
        help="Apply a tree diff patch end-to-end (temp tree, internal change request, apply, verify, cleanup)",
    )
    apply_tree_patch_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    apply_tree_patch_parser.add_argument("--tree", default=str(DEFAULT_TREE))
    apply_tree_patch_parser.add_argument(
        "--tree-patch", default=str(DEFAULT_TREE_PATCH)
    )
    apply_tree_patch_parser.add_argument("--keep-patch", action="store_true")
    apply_tree_patch_parser.add_argument(
        "--applied-patches-dir", default=str(DEFAULT_APPLIED_PATCHES_DIR)
    )
    apply_tree_patch_parser.add_argument(
        "--move-backend",
        choices=["internal", "emend"],
        default="emend",
        help="Backend used for symbol moves detected from the tree patch",
    )
    apply_tree_patch_parser.set_defaults(func=cmd_apply_tree_patch)

    apply_tree_edit_parser = subparsers.add_parser(
        "apply-tree-edit",
        help="Apply a line-number-free tree edit YAML (moves/delete_files) and reuse the same transition workflow",
    )
    apply_tree_edit_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    apply_tree_edit_parser.add_argument("--tree", default=str(DEFAULT_TREE))
    apply_tree_edit_parser.add_argument("--tree-edit", default=str(DEFAULT_TREE_EDIT))
    apply_tree_edit_parser.add_argument("--keep-patch", action="store_true")
    apply_tree_edit_parser.add_argument(
        "--applied-patches-dir", default=str(DEFAULT_APPLIED_PATCHES_DIR)
    )
    apply_tree_edit_parser.add_argument(
        "--move-backend",
        choices=["internal", "emend"],
        default="emend",
        help="Backend used for symbol moves detected from the tree edit",
    )
    apply_tree_edit_parser.set_defaults(func=cmd_apply_tree_edit)

    phase_a_parser = subparsers.add_parser(
        "candidate-phase-a",
        help="Run adapter-based candidate analysis modules and write normalized artifacts",
    )
    phase_a_parser.add_argument("--project-root", default=None)
    phase_a_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    phase_a_parser.add_argument("--project-name", default=None)
    phase_a_parser.add_argument("--cbm-binary", default=None)
    phase_a_parser.add_argument("--index-mode", default=None)
    phase_a_parser.add_argument("--max-rows", type=int, default=None)
    phase_a_parser.add_argument(
        "--semantic-terms",
        default=None,
    )
    phase_a_parser.add_argument("--semantic-limit", type=int, default=None)
    phase_a_parser.add_argument(
        "--scope-path",
        default=None,
        help="File path scope used for semantic and architecture queries",
    )
    phase_a_parser.add_argument(
        "--scope-qn-prefix",
        default=None,
        help="Qualified-name prefix used to scope dependency edge extraction",
    )
    phase_a_parser.add_argument(
        "--exclude-qn-substring",
        action="append",
        default=None,
        help="Substring filter applied to dependency source/target qualified names (repeatable)",
    )
    phase_a_parser.add_argument(
        "--include-coderag-validate",
        action="store_true",
        default=None,
    )
    phase_a_parser.add_argument(
        "--coderag-path",
        default=None,
    )
    phase_a_parser.add_argument(
        "--output-dir",
        default=None,
    )
    phase_a_parser.set_defaults(func=cmd_candidate_phase_a)

    candidate_report_parser = subparsers.add_parser(
        "candidate-report",
        help="Render candidate analysis artifacts as Markdown plus Mermaid visualizations",
    )
    candidate_report_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    candidate_report_parser.add_argument(
        "--input-dir",
        default=None,
    )
    candidate_report_parser.add_argument(
        "--output",
        default=None,
    )
    candidate_report_parser.add_argument(
        "--scope-path",
        default=None,
    )
    candidate_report_parser.add_argument(
        "--project-root",
        default=None,
    )
    candidate_report_parser.add_argument(
        "--cbm-binary",
        default=None,
    )
    demo_group = candidate_report_parser.add_mutually_exclusive_group()
    demo_group.add_argument(
        "--include-demo-artifacts",
        dest="include_demo_artifacts",
        action="store_true",
        help="Include example semantic searches and search-hit diagrams in the report",
    )
    demo_group.add_argument(
        "--no-demo-artifacts",
        dest="include_demo_artifacts",
        action="store_false",
        help="Suppress example semantic searches and search-hit diagrams in the report",
    )
    candidate_report_parser.set_defaults(include_demo_artifacts=None)
    candidate_report_parser.set_defaults(func=cmd_candidate_report)

    candidate_evaluate_parser = subparsers.add_parser(
        "candidate-evaluate",
        help="Validate candidate artifacts and write a machine-readable evaluation",
    )
    candidate_evaluate_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    candidate_evaluate_parser.add_argument("--input-dir", default=None)
    candidate_evaluate_parser.add_argument("--output", default=None)
    candidate_evaluate_parser.add_argument("--scope-path", default=None)
    candidate_evaluate_parser.add_argument("--project-root", default=None)
    candidate_evaluate_parser.add_argument("--cbm-binary", default=None)
    candidate_evaluate_parser.set_defaults(include_demo_artifacts=None)
    candidate_evaluate_parser.set_defaults(func=cmd_candidate_evaluate)

    candidate_search_parser = subparsers.add_parser(
        "candidate-search",
        help="Run CBM search_graph with defaults from candidate_analysis config",
    )
    candidate_search_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    candidate_search_parser.add_argument("--project-root", default=None)
    candidate_search_parser.add_argument("--project-name", default=None)
    candidate_search_parser.add_argument("--cbm-binary", default=None)
    candidate_search_parser.add_argument(
        "--profile",
        default=None,
        help="Name of a configured semantic_query_profile to run",
    )
    candidate_search_parser.add_argument(
        "--semantic-query",
        default=None,
        help="Semantic terms as JSON array or comma-separated list; overrides profile/config",
    )
    candidate_search_parser.add_argument("--scope-path", default=None)
    candidate_search_parser.add_argument(
        "--scope-qn-prefix",
        default=None,
        help="Qualified-name prefix used to keep dependency searches inside the configured package scope",
    )
    candidate_search_parser.add_argument(
        "--file-pattern",
        default=None,
        help="CBM file pattern; defaults to '<scope-path>/*'",
    )
    candidate_search_parser.add_argument("--label", default=None)
    candidate_search_parser.add_argument("--limit", type=int, default=None)
    candidate_search_parser.add_argument(
        "--format",
        default="json",
        choices=["json", "tree"],
    )
    candidate_search_parser.add_argument(
        "--cbm-options",
        default=None,
        help="Raw CBM flags tail as '--flag value --flag2 value2'; added after wrapper defaults",
    )
    candidate_search_parser.set_defaults(func=cmd_candidate_search)

    internal_parser = subparsers.add_parser(
        "internal-dependencies-report",
        help="Report internal module dependencies, cycles, fan-in, and fan-out",
    )
    internal_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    internal_parser.add_argument("--project-root", default=None)
    internal_parser.add_argument("--scope-path", default=None)
    internal_parser.add_argument("--output-dir", default=None)
    internal_parser.set_defaults(func=cmd_internal_dependencies_report)

    quality_parser = subparsers.add_parser(
        "quality-gate",
        help="Generate a complexity report and enforce regression thresholds against a baseline",
    )
    quality_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    quality_parser.add_argument("--project-root", default=None)
    quality_parser.add_argument("--scope-path", default=None)
    quality_parser.add_argument("--paths", nargs="+", default=None)
    quality_parser.add_argument("--output-dir", default=None)
    quality_parser.add_argument("--refresh-baseline", action="store_true")
    quality_parser.add_argument("--no-coverage", action="store_true")
    quality_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Always run the coverage command instead of reusing fresh coverage data",
    )
    quality_parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="Return non-zero when the baseline is missing or the quality gate fails",
    )
    quality_parser.set_defaults(func=cmd_quality_gate)

    legacy_quality_parser = subparsers.add_parser(
        "quality-report",
        help="Compatibility alias for quality-gate",
    )
    legacy_quality_parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    legacy_quality_parser.add_argument("--project-root", default=None)
    legacy_quality_parser.add_argument("--scope-path", default=None)
    legacy_quality_parser.add_argument("--paths", nargs="+", default=None)
    legacy_quality_parser.add_argument("--output-dir", default=None)
    legacy_quality_parser.add_argument("--refresh-baseline", action="store_true")
    legacy_quality_parser.add_argument("--no-coverage", action="store_true")
    legacy_quality_parser.add_argument("--no-cache", action="store_true")
    legacy_quality_parser.add_argument("--fail-on-gate", action="store_true")
    legacy_quality_parser.set_defaults(func=cmd_quality_report)

    return parser
