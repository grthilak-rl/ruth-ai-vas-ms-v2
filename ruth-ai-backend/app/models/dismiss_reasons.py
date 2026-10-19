"""Why a violation was dismissed.

Dismissing is the operator saying "this should not have fired" — or, for
duplicates, "this is handled elsewhere". The reason matters downstream: a
false alarm is a training example the model got wrong, so false-alarm
dismissals copy the inferred frame to the labelling set for the AI
engineer (see app/services/false_positive_export.py).

Stored as plain text (violations.dismiss_reason), not a Postgres enum, so a
new reason is a code change rather than a migration.
"""

from enum import Enum


class DismissReason(str, Enum):
    #: Pipework, an object or a shadow taken for the target.
    OBJECT = "object"
    #: A real person, but not the one the rule is about.
    WRONG_PERSON = "wrong_person"
    #: The PPE the model said was missing is actually worn.
    PPE_WORN = "ppe_worn"
    #: Another kind of false alarm; a note is required.
    OTHER_FALSE_ALARM = "other_false_alarm"
    #: Not a false alarm: a duplicate, or already handled.
    DUPLICATE = "duplicate"


REASON_LABELS: dict[DismissReason, str] = {
    DismissReason.OBJECT: "Pipework / object",
    DismissReason.WRONG_PERSON: "Wrong person",
    DismissReason.PPE_WORN: "PPE actually worn",
    DismissReason.OTHER_FALSE_ALARM: "Other false alarm",
    DismissReason.DUPLICATE: "Duplicate / already handled",
}

#: Reasons that mean the model was wrong: exported for labelling.
FALSE_ALARM_REASONS: frozenset[DismissReason] = frozenset(
    {
        DismissReason.OBJECT,
        DismissReason.WRONG_PERSON,
        DismissReason.PPE_WORN,
        DismissReason.OTHER_FALSE_ALARM,
    }
)

#: Reasons where the frame contains none of the model's target, so it is a
#: true background image for that model: an empty YOLO label file is written
#: alongside. Not "wrong person" (someone is there, possibly a valid target
#: for the class) nor "other" (unknown).
YOLO_BACKGROUND_REASONS: frozenset[DismissReason] = frozenset(
    {DismissReason.OBJECT, DismissReason.PPE_WORN}
)

#: Reasons that need a note to make sense.
NOTE_REQUIRED_REASONS: frozenset[DismissReason] = frozenset({DismissReason.OTHER_FALSE_ALARM})
