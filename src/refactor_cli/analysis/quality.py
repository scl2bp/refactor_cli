from __future__ import annotations

from typing import Any


def quality_summary(*, total: int, affected: int) -> dict[str, Any]:
    """Return a transparent coverage and degradation summary."""
    total = max(int(total), 0)
    affected = min(max(int(affected), 0), total) if total else 0
    accepted = total - affected
    if total == 0:
        return {
            "affected": 0,
            "total": 0,
            "accepted": 0,
            "coverage_percent": None,
            "loss_percent": None,
            "grade": "NOT_MEASURABLE",
        }

    coverage = accepted / total * 100
    loss = affected / total * 100
    if affected == 0:
        grade = "NONE"
    elif loss <= 1:
        grade = "MINOR"
    elif loss <= 5:
        grade = "MODERATE"
    elif loss <= 20:
        grade = "MAJOR"
    else:
        grade = "CRITICAL"
    return {
        "affected": affected,
        "total": total,
        "accepted": accepted,
        "coverage_percent": round(coverage, 2),
        "loss_percent": round(loss, 2),
        "grade": grade,
    }