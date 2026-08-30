"""Canonical units for promoted benchmark scores."""
from __future__ import annotations


_PERCENTAGE_METRICS = {
    "accuracy",
    "f1",
    "pass_rate",
    "pass_rate_2",
    "percent",
    "percent_correct",
    "percent_resolved",
    "percentage",
}


def is_percentage_metric(metric: str | None) -> bool:
    """Return whether a canonical benchmark metric uses percentage points."""
    if not metric:
        return False
    normalized = metric.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in _PERCENTAGE_METRICS or normalized.startswith("percent_")


def canonicalize_fractional_score(score: float, metric: str | None) -> float:
    """Convert 0-1 fractions while preserving scores already in canonical units."""
    if is_percentage_metric(metric) and abs(score) <= 1:
        return score * 100
    return score
