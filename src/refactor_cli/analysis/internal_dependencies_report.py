"""Internal module dependency report compatibility surface."""

from refactor_cli.analysis.quality_report import (
    collect_quality_report,
    render_quality_report,
    write_quality_report,
)

__all__ = [
    "collect_quality_report",
    "render_quality_report",
    "write_quality_report",
]