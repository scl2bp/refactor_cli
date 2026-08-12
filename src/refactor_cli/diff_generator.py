"""
Diff generation for refactoring operations.
"""

from pathlib import Path
from typing import List, Tuple


class DiffGenerator:
    """Generate diffs showing proposed changes."""

    def generate_extraction_diff(
        self, source_file: Path, extracted_symbols: List[str], target_file: Path
    ) -> str:
        """Generate a diff showing extraction of symbols."""
        diff_lines = []
        diff_lines.append(f"--- {source_file} (original)")
        diff_lines.append(f"+++ {source_file} (refactored)")
        diff_lines.append("")

        diff_lines.append(f"Create new file: {target_file}")
        diff_lines.append(f"Move {len(extracted_symbols)} symbols:")
        for symbol in extracted_symbols:
            diff_lines.append(f"  + {symbol}")

        diff_lines.append("")
        diff_lines.append(f"Update imports in {source_file}:")
        diff_lines.append(f"  + from {target_file.stem} import (")
        for symbol in extracted_symbols:
            diff_lines.append(f"      {symbol},")
        diff_lines.append(f"  )")

        return "\n".join(diff_lines)

    def compare_files(self, original: str, modified: str) -> List[str]:
        """Generate unified diff between two strings."""
        import difflib

        orig_lines = original.splitlines(keepends=True)
        mod_lines = modified.splitlines(keepends=True)

        diff = difflib.unified_diff(
            orig_lines, mod_lines, fromfile="original", tofile="modified", lineterm=""
        )

        return list(diff)
