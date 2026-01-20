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
