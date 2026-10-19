"""Human labels for violation types.

A violation has a family (``type``: one of four enum members) and, usually,
a specific type (``type_detail``: the model's own string, e.g.
``missing_gloves``). The UI shows both — "PPE Violation · Missing gloves" —
and analytics/export break families down by specific type, so every surface
needs the same answer to "what is this called".

Labels are resolved at read time, never stored: a ``display_name`` added to
or edited in a manifest relabels past violations too, and no migration is
involved. Order of precedence for a specific type:

1. The ``display_name`` of the manifest rule that emits it — the violation's
   own model first, then any installed store model.
2. A built-in label for the types the platform already knows.
3. Title-cased ``type_detail``, for anything else (an unmapped string, or a
   bare model_id the write path fell back to).

A violation with no specific type has no specific label; it is shown under
its family alone ("Fall Detected").
"""

from typing import Mapping, Optional

from app.models.enums import VIOLATION_TYPE_MAP, ViolationType
from app.services.model_store.enabled import StoreModelInfo, enabled_store_models
from app.services.violation_severity import normalize_severity, resolve_severity

#: Separator between family and specific label in a combined label.
LABEL_SEPARATOR = " · "

FAMILY_LABELS: dict[str, str] = {
    ViolationType.FALL_DETECTED.value: "Fall Detected",
    ViolationType.PPE_VIOLATION.value: "PPE Violation",
    ViolationType.ZONE_INTRUSION.value: "Zone Intrusion",
    ViolationType.ZONE_EXIT.value: "Zone Exit",
}

#: The specific values the write path already knows (VIOLATION_TYPE_MAP
#: entries other than the family values themselves).
VIOLATION_TYPE_MAP_DETAILS: frozenset[str] = frozenset(
    raw for raw, family in VIOLATION_TYPE_MAP.items() if raw != family.value
)

#: A polished label for each of VIOLATION_TYPE_MAP_DETAILS (a unit test keeps
#: the two in step). A manifest display_name still wins over these.
BUILTIN_DETAIL_LABELS: dict[str, str] = {
    "missing_hardhat": "Missing hard hat",
    "missing_vest": "Missing safety vest",
    "missing_goggles": "Missing goggles",
    "missing_mask": "Missing mask",
    "missing_gloves": "Missing gloves",
    "missing_harness": "Missing safety harness",
    "possible_fall": "Possible fall",
    "tank_overflow_warning": "Tank overflow warning",
    "tank_critical_high": "Tank level critically high",
    "tank_critical_low": "Tank level critically low",
}


def title_case(value: str) -> str:
    """``missing_safety_boots`` -> ``Missing Safety Boots``."""
    return " ".join(part.capitalize() for part in value.replace("-", "_").split("_") if part)


def _value(type_: ViolationType | str) -> str:
    return type_.value if isinstance(type_, ViolationType) else str(type_)


class ViolationLabeler:
    """Resolves labels against one snapshot of the installed store models.

    Build one per request (``ViolationLabeler.current()``) and reuse it for
    every row, so a list of a thousand violations reads the manifests once.
    """

    def __init__(self, store_models: Mapping[str, StoreModelInfo] | None = None):
        self._store_models: Mapping[str, StoreModelInfo] = store_models or {}

    @classmethod
    def current(cls) -> "ViolationLabeler":
        return cls(enabled_store_models())

    def family_label(self, type_: ViolationType | str) -> str:
        value = _value(type_)
        return FAMILY_LABELS.get(value) or title_case(value)

    def detail_label(self, type_detail: str | None, model_id: str | None = None) -> Optional[str]:
        if not type_detail:
            return None
        detail = type_detail.strip().lower()

        own = self._store_models.get(model_id) if model_id else None
        if own is not None and (label := own.rule_label(detail)):
            return label
        # Aggregates (analytics, filter options) span models, and a violation
        # from a model whose manifest is gone can still be named by another
        # model that emits the same type. Sorted for a stable answer.
        for model_key in sorted(self._store_models):
            if label := self._store_models[model_key].rule_label(detail):
                return label

        return BUILTIN_DETAIL_LABELS.get(detail) or title_case(detail)

    def combined_label(
        self,
        type_: ViolationType | str,
        type_detail: str | None,
        model_id: str | None = None,
    ) -> str:
        """``PPE Violation · Missing gloves``, or just the family label."""
        family = self.family_label(type_)
        detail = self.detail_label(type_detail, model_id)
        return f"{family}{LABEL_SEPARATOR}{detail}" if detail else family

    def short_label(
        self,
        type_: ViolationType | str,
        type_detail: str | None,
        model_id: str | None = None,
    ) -> str:
        """The most specific label alone, for narrow columns."""
        return self.detail_label(type_detail, model_id) or self.family_label(type_)

    def severity(self, violation) -> str:
        """Stored severity, or resolved now for rows written without one."""
        return normalize_severity(getattr(violation, "severity", None)) or resolve_severity(
            type_=violation.type,
            type_detail=violation.type_detail,
            model_id=getattr(violation, "model_id", None),
            store_models=self._store_models,
        )

    def type_fields(self, violation) -> dict:
        """The type fields every violation response carries."""
        return {
            "type": _value(violation.type),
            "type_detail": violation.type_detail,
            "type_label": self.family_label(violation.type),
            "detail_label": self.detail_label(violation.type_detail, violation.model_id),
            "severity": self.severity(violation),
        }
