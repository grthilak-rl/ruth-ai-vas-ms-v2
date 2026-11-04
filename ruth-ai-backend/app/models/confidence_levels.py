"""Confidence buckets: the one place the Low/Medium/High cut-offs live.

Confidence is how sure the model was, as the model reported it — not the
rule's severity. The UI never shows the number (F6 §3.2), only the bucket,
so the bucket is computed here and sent with every violation, and the
Violations page filters on it with the same cut-offs.

Most violations never land in Low: a violation is only written once its
confidence clears the creation threshold (the session's, 0.7 by default,
or a store model's manifest floor), so Low only fills up when a manifest
floor sits below MEDIUM_FROM.
"""

from collections.abc import Iterable

from sqlalchemy import and_, or_

#: Bucket lower bounds, inclusive. Below MEDIUM_FROM is Low.
HIGH_FROM = 0.8
MEDIUM_FROM = 0.6

#: Most to least confident.
CONFIDENCE_LEVELS: tuple[str, ...] = ("high", "medium", "low")

_LABELS = {"high": "High", "medium": "Medium", "low": "Low"}


def confidence_level(confidence: float | None) -> str:
    """'high', 'medium' or 'low' for a model confidence (None counts as 0)."""
    value = confidence or 0.0
    if value >= HIGH_FROM:
        return "high"
    if value >= MEDIUM_FROM:
        return "medium"
    return "low"


def confidence_label(confidence: float | None) -> str:
    """'High', 'Medium' or 'Low', for exports."""
    return _LABELS[confidence_level(confidence)]


def normalize_confidence_levels(values: Iterable[str]) -> list[str]:
    """The known levels among ``values``, de-duplicated, in canonical order."""
    wanted = {str(v).strip().lower() for v in values}
    return [level for level in CONFIDENCE_LEVELS if level in wanted]


def confidence_condition(column, levels: Iterable[str]):
    """A SQL condition: ``column`` falls in any of ``levels``.

    Adjacent buckets merge into one range, so High+Medium is a single
    ``>= MEDIUM_FROM`` rather than an OR of two ranges.
    """
    chosen = set(normalize_confidence_levels(levels))
    if not chosen or chosen == set(CONFIDENCE_LEVELS):
        return None
    bounds = {"low": (None, MEDIUM_FROM), "medium": (MEDIUM_FROM, HIGH_FROM), "high": (HIGH_FROM, None)}
    ranges: list[list] = []
    for level in ("low", "medium", "high"):  # ascending, to merge neighbours
        if level not in chosen:
            continue
        lo, hi = bounds[level]
        if ranges and ranges[-1][1] == lo:
            ranges[-1][1] = hi
        else:
            ranges.append([lo, hi])
    parts = []
    for lo, hi in ranges:
        conds = []
        if lo is not None:
            conds.append(column >= lo)
        if hi is not None:
            conds.append(column < hi)
        parts.append(and_(*conds))
    return parts[0] if len(parts) == 1 else or_(*parts)
