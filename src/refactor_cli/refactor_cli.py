#!/usr/bin/env python3
"""
Mobiliti Refactoring CLI Tool

Deterministic refactoring using LibCST and other syntax-aware tools.
Generates diffs and transformations without modifying files directly.

Usage:
    python -m refactor_cli.refactor_cli extract-constants main.py
    python -m refactor_cli.refactor_cli extract-parking main.py
    python -m refactor_cli.refactor_cli show-structure main.py
"""

import argparse
from pathlib import Path

import libcst as cst

from refactor_cli.extractors import (
    ConstantExtractor,
    ParkingDomainExtractor,
    CodeStructureAnalyzer,
)
from refactor_cli.diff_generator import DiffGenerator


def cmd_extract_constants(args):
    """Extract regex constants from a Python file."""
    source_file = Path(args.file)

    if not source_file.exists():
        print(f"Error: File not found: {source_file}")
        return 1

    code = source_file.read_text()
    tree = cst.parse_module(code)

    extractor = ConstantExtractor()
    tree.visit(extractor)

    if not extractor.regex_constants:
        print(f"No regex constants found in {source_file}")
        return 0

    print(f"=== REGEX CONSTANTS FOUND ===\n")
    print(f"File: {source_file}")
    print(f"Total found: {len(extractor.regex_constants)}\n")

    for const_name, const_value in extractor.regex_constants.items():
        print(f"  {const_name}")
        print(
            f"    Value: {const_value[:60]}..."
            if len(const_value) > 60
            else f"    Value: {const_value}"
        )
        print()

    # Generate diffs
    diff_gen = DiffGenerator()
    target_module = args.output or f"src/mobiliti/constants.py"

    print(f"\n=== PROPOSED CHANGES ===\n")
    print(f"1. Create new module: {target_module}")
    print(f"   (with {len(extractor.regex_constants)} regex constants)")
    print(f"\n2. Update imports in: {source_file.name}")
    print(
        f"   Add: from {Path(target_module).stem} import {', '.join(extractor.regex_constants.keys())}"
    )

    return 0


def cmd_extract_parking(args):
    """Extract parking domain (classes, functions, constants) from main.py."""
    source_file = Path(args.file)

    if not source_file.exists():
        print(f"Error: File not found: {source_file}")
        return 1

    code = source_file.read_text()
    tree = cst.parse_module(code)

    extractor = ParkingDomainExtractor()
    tree.visit(extractor)

    print(f"=== PARKING DOMAIN EXTRACTION ANALYSIS ===\n")
    print(f"Source: {source_file}\n")

    print(f"Classes to extract ({len(extractor.classes)}):")
    for cls_name in extractor.classes:
        print(f"  ✓ {cls_name}")

    print(f"\nConstants to extract ({len(extractor.constants)}):")
    for const_name in sorted(extractor.constants):
        print(f"  ✓ {const_name}")

    print(f"\nFunctions to extract ({len(extractor.functions)}):")
    for func_name in extractor.functions:
        print(f"  ✓ {func_name}")

    total_symbols = (
        len(extractor.classes) + len(extractor.constants) + len(extractor.functions)
    )
    print(f"\nTotal symbols: {total_symbols}")

    # Calculate approximate line count
    parking_functions = [
        "parse_dms",
        "parse_segments",
        "parse_parking_file",
        "interpolate",
        "bilinear_interpolate",
        "get_google_maps_url",
        "get_google_maps_box_url",
        "command_url_get",
        "command_url_box",
    ]
    matching = sum(1 for f in parking_functions if f in extractor.functions)
    print(f"Parking-specific functions found: {matching}/{len(parking_functions)}")

    print(f"\n=== PROPOSED TRANSFORMATION ===")
    target_module = args.output or "src/mobiliti/parking.py"
    print(f"\nCreate: {target_module}")
    print(f"  - Move {len(extractor.classes)} dataclasses")
    print(f"  - Move {len(extractor.constants)} regex constants")
    print(f"  - Move {matching} parking functions")
    print(f"\nUpdate: {source_file.name}")
    print(f"  - Add import statement for parking domain")
    print(f"  - Remove extracted symbols")

    return 0


def cmd_show_structure(args):
    """Analyze and display code structure."""
    source_file = Path(args.file)

    if not source_file.exists():
        print(f"Error: File not found: {source_file}")
        return 1

    code = source_file.read_text()
    tree = cst.parse_module(code)

    analyzer = CodeStructureAnalyzer()
    tree.visit(analyzer)

    print(f"=== CODE STRUCTURE: {source_file} ===\n")
    print(f"Total lines: {len(code.splitlines())}")
    print(f"Classes: {len(analyzer.classes)}")
    print(f"Functions: {len(analyzer.functions)}")
    print(f"Imports: {len(analyzer.imports)}")
    print(f"Constants: {len(analyzer.constants)}\n")

    print("Classes:")
    for cls_name in analyzer.classes[:10]:
        print(f"  - {cls_name}")
    if len(analyzer.classes) > 10:
        print(f"  ... and {len(analyzer.classes) - 10} more")

    print("\nFunctions (first 20):")
    for func_name in analyzer.functions[:20]:
        print(f"  - {func_name}")
    if len(analyzer.functions) > 20:
        print(f"  ... and {len(analyzer.functions) - 20} more")

    print("\nConstants (regex and configuration):")
    for const_name in sorted(analyzer.constants):
        print(f"  - {const_name}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Mobiliti Deterministic Refactoring Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Extract regex constants:
        python -m refactor_cli.refactor_cli extract-constants main.py
  
  Extract parking domain:
        python -m refactor_cli.refactor_cli extract-parking main.py --output src/mobiliti/parking.py
  
  Analyze code structure:
        python -m refactor_cli.refactor_cli show-structure main.py
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Refactoring operation")

    # extract-constants command
    constants_parser = subparsers.add_parser(
        "extract-constants", help="Extract regex constants to a new module"
    )
    constants_parser.add_argument("file", help="Target Python file")
    constants_parser.add_argument("--output", help="Output module path")
    constants_parser.set_defaults(func=cmd_extract_constants)

    # extract-parking command
    parking_parser = subparsers.add_parser(
        "extract-parking", help="Extract parking domain to a new module"
    )
    parking_parser.add_argument("file", help="Target Python file")
    parking_parser.add_argument("--output", help="Output module path")
    parking_parser.set_defaults(func=cmd_extract_parking)

    # show-structure command
    structure_parser = subparsers.add_parser(
        "show-structure", help="Analyze and display code structure"
    )
    structure_parser.add_argument("file", help="Target Python file")
    structure_parser.set_defaults(func=cmd_show_structure)

    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
