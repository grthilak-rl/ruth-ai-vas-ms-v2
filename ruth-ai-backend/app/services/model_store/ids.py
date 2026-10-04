"""model_id rules for uploaded models.

A model_id becomes the runtime model id, a directory name and a key the rest
of the platform routes on, so it is deliberately narrow:

- ``^[a-z][a-z0-9_]{2,47}$``
- never one of the ids the existing runtime or backend already use
- never a prefix the backend's /models/status hides (test_, dummy_, broken_)
- unique forever: deleted models keep their row, so their id stays taken
"""

import re

MODEL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,47}$")
MODEL_ID_MAX_LENGTH = 48

#: Ids already owned by the platform: the five runtime models, the backend's
#: routing table entries, and the unversioned chane prototype directory.
RESERVED_MODEL_IDS = frozenset(
    {
        "fall_detection",
        "ppe_detection",
        "geo_fencing",
        "tank_overflow_monitoring",
        "chane_tank_monitor",
        "chane_tank_overflow",
        "helmet_detection",
        "fire_detection",
        "intrusion_detection",
    }
)

#: The backend's GET /models/status drops ids with these prefixes.
RESERVED_PREFIXES = ("test_", "dummy_", "broken_")


def model_id_problem(model_id: str) -> str | None:
    """Why ``model_id`` is not acceptable, or None. Uniqueness is checked by the caller."""
    if not MODEL_ID_PATTERN.match(model_id):
        return (
            "model_id must be 3-48 characters: a lowercase letter, then lowercase "
            "letters, digits or underscores"
        )
    if model_id in RESERVED_MODEL_IDS:
        return f"model_id '{model_id}' is reserved by an existing platform model"
    if model_id.startswith(RESERVED_PREFIXES):
        return f"model_id must not start with {', '.join(RESERVED_PREFIXES)}"
    return None


def model_id_base_from_name(display_name: str) -> str:
    """A valid model_id stem derived from a display name (before uniqueness)."""
    slug = re.sub(r"[^a-z0-9]+", "_", display_name.lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"model_{slug}".rstrip("_")
    if slug.startswith(RESERVED_PREFIXES):
        slug = f"model_{slug}"
    if len(slug) < 3:
        slug = f"{slug}_model"
    # Leave room for a _NN uniqueness suffix.
    return slug[: MODEL_ID_MAX_LENGTH - 4].rstrip("_")


def model_id_candidates(display_name: str, attempts: int = 99):
    """Yield model_id candidates: the base, then base_2, base_3, ..."""
    base = model_id_base_from_name(display_name)
    yield base
    for n in range(2, attempts + 1):
        yield f"{base}_{n}"
