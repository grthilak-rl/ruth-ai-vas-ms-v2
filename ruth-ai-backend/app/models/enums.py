"""Database enums for Ruth AI.

All enum values are lowercase to match:
1. VAS API reality (stream states are lowercase: 'live', 'stopped')
2. Ruth AI API Contract Specification (event_type, violation_status, etc.)

These enums are persisted as PostgreSQL ENUM types for data integrity.
"""

import enum


class StreamState(str, enum.Enum):
    """Stream lifecycle states.

    Matches VAS stream states (lowercase per CLAUDE.md).
    """

    LIVE = "live"
    STOPPED = "stopped"
    STARTING = "starting"
    STOPPING = "stopping"
    ERROR = "error"


class EventType(str, enum.Enum):
    """AI detection event types.

    From API Contract Section 3.1 - Event Schema.
    """

    # Fall Detection Events
    FALL_DETECTED = "fall_detected"
    NO_FALL = "no_fall"
    PERSON_DETECTED = "person_detected"

    # PPE Detection Events
    PPE_VIOLATION = "ppe_violation"
    PPE_COMPLIANT = "ppe_compliant"

    UNKNOWN = "unknown"


class ViolationType(str, enum.Enum):
    """Violation types (derived from event types).

    From API Contract Section 3.2 - Violation Schema.
    Future types: intrusion, fire, etc.
    """

    FALL_DETECTED = "fall_detected"
    PPE_VIOLATION = "ppe_violation"
    ZONE_INTRUSION = "zone_intrusion"  # Geo-fencing: person entered restricted zone
    ZONE_EXIT = "zone_exit"  # Geo-fencing: person left allowed zone


# ---------------------------------------------------------------------------
# Model vocabulary -> enum reconciliation
# ---------------------------------------------------------------------------
# The AI models emit a larger and independently-evolving set of violation
# strings than this enum holds. Writing those straight into the enum column
# fails the insert, and because the failure is per-row it silently DROPS real
# safety violations — it was losing ~80% of writes when found.
#
# The vocabulary is mapped here rather than added to the enum: four separately
# authored models each choose their own strings, the PPE detector already
# recognises classes (gloves, boots) not yet in its violation logic, and the
# write path can fall back to an arbitrary model_id. Coupling the schema to
# that means a migration per model change, and silent data loss for every one
# that gets missed.
#
# The specific value is preserved in violations.type_detail, so nothing is
# lost: `type` answers "what class of violation", `type_detail` answers
# "which PPE item".
VIOLATION_TYPE_MAP: dict[str, ViolationType] = {
    # PPE — the model narrows to the specific missing item
    "ppe_violation": ViolationType.PPE_VIOLATION,
    "missing_hardhat": ViolationType.PPE_VIOLATION,
    "missing_vest": ViolationType.PPE_VIOLATION,
    "missing_goggles": ViolationType.PPE_VIOLATION,
    "missing_mask": ViolationType.PPE_VIOLATION,
    # Fall — "possible_fall" is a lower-confidence fall, not a separate class.
    # The distinction survives in type_detail and in `confidence`.
    "fall_detected": ViolationType.FALL_DETECTED,
    "possible_fall": ViolationType.FALL_DETECTED,
    # Geo-fencing — already enum members, mapped for completeness so every
    # known emitted value resolves through one table.
    "zone_intrusion": ViolationType.ZONE_INTRUSION,
    "zone_exit": ViolationType.ZONE_EXIT,
    # Tank overflow — no dedicated enum member exists. These are threshold
    # breaches on monitored equipment, classified as zone_intrusion (the
    # closest "monitored condition exceeded" member) with the severity
    # preserved in type_detail. Worth revisiting if tank monitoring becomes a
    # primary workflow and deserves its own member.
    "tank_overflow_warning": ViolationType.ZONE_INTRUSION,
    "tank_critical_high": ViolationType.ZONE_INTRUSION,
    "tank_critical_low": ViolationType.ZONE_INTRUSION,
}

# Where an unrecognised value lands. Chosen because an unknown detection is
# still a detection: storing it under a generic type keeps the evidence, the
# timestamp and the camera, which is strictly better than dropping the row.
UNKNOWN_VIOLATION_TYPE = ViolationType.PPE_VIOLATION


def resolve_violation_type(raw_type: str | None) -> tuple[ViolationType, str | None]:
    """Map a model's violation string onto the enum, never raising.

    Args:
        raw_type: Whatever the model reported. May be None, an enum member's
            value, a more specific string, or — via the write path's fallback
            — a bare model_id.

    Returns:
        (enum_member, type_detail). ``type_detail`` is the original string when
        it carried more information than the enum member, else None.

        The caller is expected to log unmapped values; this function stays
        pure so it is trivially testable. Use ``is_known_violation_type`` to
        decide whether to warn.
    """
    if not raw_type:
        return UNKNOWN_VIOLATION_TYPE, None

    normalized = str(raw_type).strip().lower()
    mapped = VIOLATION_TYPE_MAP.get(normalized)

    if mapped is None:
        # Unknown: keep the row, keep the original string for diagnosis.
        return UNKNOWN_VIOLATION_TYPE, normalized[:64]

    # Only record detail when it says more than the enum member already does.
    detail = None if normalized == mapped.value else normalized[:64]
    return mapped, detail


def is_known_violation_type(raw_type: str | None) -> bool:
    """Whether a model's violation string is one we recognise."""
    if not raw_type:
        return False
    return str(raw_type).strip().lower() in VIOLATION_TYPE_MAP


class ViolationStatus(str, enum.Enum):
    """Violation lifecycle statuses.

    From API Contract Section 3.2 - ViolationStatus.
    Status transitions are enforced:
    - open → reviewed, dismissed
    - reviewed → dismissed, resolved
    - dismissed → open (re-open)
    - resolved → (terminal, no transitions)
    """

    OPEN = "open"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"


class EvidenceType(str, enum.Enum):
    """Types of evidence that can be captured.

    Evidence is captured via VAS APIs (snapshots, bookmarks).
    """

    SNAPSHOT = "snapshot"
    BOOKMARK = "bookmark"


class EvidenceStatus(str, enum.Enum):
    """Evidence processing status.

    From API Contract Section 3.3 - EvidenceStatus.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class BookmarkAnalysisState(str, enum.Enum):
    """Bookmark analysis job lifecycle.

    Used by the bookmark_analyses table (Phase D.1+). Each analysis row
    is an async job submitted against a VAS bookmark; the worker
    transitions pending → running → completed/failed.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
