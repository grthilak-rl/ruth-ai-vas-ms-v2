"""Violation severity: how bad the rule that fired says it is.

Severity is the *rule's* judgement (a missing harness is critical, missing
goggles high), set by whoever wrote the model's manifest. It is not
confidence, which is how sure the model is; the Violations page showed only
confidence, styled like a severity.

Stored on the violation when it is written, so it records what the rule said
at the time, then resolved in this order:

1. The severity the model reported with the detection (the store plugin
   sends its firing rule's, highest wins when several fire).
2. The manifest rule for the violation's specific type — the violation's own
   model first, then any installed store model.
3. A built-in default, for the models without manifests (fall, built-in PPE,
   tank) — by specific type, then by family.
4. "medium".

Rows written before the column existed were backfilled by the migration;
anything still NULL (e.g. restored from an archive) resolves at read time.
"""

from typing import Mapping, Optional

from app.models.enums import ViolationType
from app.services.model_store.enabled import StoreModelInfo

#: Most to least severe.
SEVERITY_LEVELS: tuple[str, ...] = ("critical", "high", "medium", "low")

#: Higher is more severe; for "worst of an incident" and sorting.
SEVERITY_RANK: dict[str, int] = {
    level: len(SEVERITY_LEVELS) - i for i, level in enumerate(SEVERITY_LEVELS)
}

DEFAULT_SEVERITY = "medium"

#: Built-in models have no manifest. Specific types first, then families.
BUILTIN_SEVERITY: dict[str, str] = {
    "possible_fall": "high",
    "tank_critical_high": "critical",
    "tank_critical_low": "critical",
    "tank_overflow_warning": "high",
    ViolationType.FALL_DETECTED.value: "critical",
    ViolationType.PPE_VIOLATION.value: "high",
    ViolationType.ZONE_INTRUSION.value: "high",
    ViolationType.ZONE_EXIT.value: "medium",
}


def normalize_severity(value: object) -> Optional[str]:
    """A known severity level, or None for anything else."""
    if not isinstance(value, str):
        return None
    level = value.strip().lower()
    return level if level in SEVERITY_RANK else None


def resolve_severity(
    *,
    reported: object = None,
    type_: ViolationType | str,
    type_detail: str | None,
    model_id: str | None,
    store_models: Mapping[str, StoreModelInfo] | None = None,
) -> str:
    """The severity to record or show for a violation. Never raises."""
    if level := normalize_severity(reported):
        return level

    family = type_.value if isinstance(type_, ViolationType) else str(type_)
    detail = (type_detail or "").strip().lower() or None
    models = store_models or {}

    if detail:
        own = models.get(model_id) if model_id else None
        if own is not None and (level := normalize_severity(own.rule_severity(detail))):
            return level
        for key in sorted(models):
            if level := normalize_severity(models[key].rule_severity(detail)):
                return level
        if detail in BUILTIN_SEVERITY:
            return BUILTIN_SEVERITY[detail]

    return BUILTIN_SEVERITY.get(family, DEFAULT_SEVERITY)


def worst_severity(levels) -> str:
    """The most severe of several levels (an incident's badge)."""
    known = [lvl for lvl in (normalize_severity(x) for x in levels) if lvl]
    return max(known, key=SEVERITY_RANK.__getitem__) if known else DEFAULT_SEVERITY
