"""Violation labels: manifest > built-in > title-case, and the breakdowns
(type filter options, analytics by type, CSV export) that use them.
"""

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.api.v1.analytics import build_type_breakdown
from app.api.v1.violations import build_type_options
from app.models.enums import ViolationStatus, ViolationType
from app.services.export_service import ExportService
from app.services.model_store.enabled import StoreModelInfo, read_enabled_models
from app.services.violation_labels import (
    BUILTIN_DETAIL_LABELS,
    VIOLATION_TYPE_MAP_DETAILS,
    ViolationLabeler,
    title_case,
)

PPE = ViolationType.PPE_VIOLATION
FALL = ViolationType.FALL_DETECTED
ZONE = ViolationType.ZONE_INTRUSION


def store(model_id: str, *labels: tuple[str, str]) -> StoreModelInfo:
    return StoreModelInfo(model_id=model_id, version="1.0.0", display_name=model_id, rule_labels=labels)


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------


def test_family_labels():
    labeler = ViolationLabeler()
    assert labeler.family_label(FALL) == "Fall Detected"
    assert labeler.family_label("ppe_violation") == "PPE Violation"
    assert labeler.family_label(ZONE) == "Zone Intrusion"
    assert labeler.family_label(ViolationType.ZONE_EXIT) == "Zone Exit"


def test_no_detail_means_family_only():
    labeler = ViolationLabeler()
    assert labeler.detail_label(None) is None
    assert labeler.detail_label("") is None
    assert labeler.combined_label(FALL, None) == "Fall Detected"
    assert labeler.short_label(FALL, None) == "Fall Detected"


def test_builtin_labels_cover_every_known_specific_type():
    # Every specific value the write path maps must have a polished label,
    # so only genuinely unknown strings fall through to title-case.
    assert VIOLATION_TYPE_MAP_DETAILS <= set(BUILTIN_DETAIL_LABELS)
    labeler = ViolationLabeler()
    assert labeler.detail_label("missing_hardhat") == "Missing hard hat"
    assert labeler.detail_label("possible_fall") == "Possible fall"
    assert labeler.detail_label("tank_critical_high") == "Tank level critically high"
    assert labeler.combined_label(ZONE, "tank_overflow_warning") == "Zone Intrusion · Tank overflow warning"


def test_unknown_detail_is_title_cased():
    labeler = ViolationLabeler()
    assert title_case("missing_safety_boots") == "Missing Safety Boots"
    assert labeler.detail_label("missing_safety_boots") == "Missing Safety Boots"
    # A bare model_id the write path fell back to.
    assert labeler.combined_label(PPE, "hard_hat") == "PPE Violation · Hard Hat"


def test_manifest_display_name_wins_own_model_first():
    labeler = ViolationLabeler(
        {
            "gloves": store("gloves", ("missing_gloves", "Gloves off")),
            "gloves_2": store("gloves_2", ("missing_gloves", "No gloves")),
        }
    )
    assert labeler.detail_label("missing_gloves", "gloves_2") == "No gloves"
    assert labeler.detail_label("missing_gloves", "gloves") == "Gloves off"
    # No model given (aggregates) or the model has no label: first installed
    # store model, in model_id order, that names it.
    assert labeler.detail_label("missing_gloves") == "Gloves off"
    assert labeler.detail_label("missing_gloves", "fall_detection") == "Gloves off"
    assert labeler.combined_label(PPE, "missing_gloves", "gloves_2") == "PPE Violation · No gloves"


def test_manifest_without_label_falls_back_to_builtin():
    labeler = ViolationLabeler({"hard_hat": store("hard_hat")})
    assert labeler.detail_label("missing_hardhat", "hard_hat") == "Missing hard hat"


def test_type_fields_for_a_response():
    labeler = ViolationLabeler({"gloves_2": store("gloves_2", ("missing_gloves", "Missing gloves"))})
    v = SimpleNamespace(type=PPE, type_detail="missing_gloves", model_id="gloves_2")
    assert labeler.type_fields(v) == {
        "type": "ppe_violation",
        "type_detail": "missing_gloves",
        "type_label": "PPE Violation",
        "detail_label": "Missing gloves",
        "severity": "high",  # no manifest severity given -> PPE family default
    }
    fall = SimpleNamespace(type=FALL, type_detail=None, model_id="fall_detection")
    assert labeler.type_fields(fall)["detail_label"] is None
    assert labeler.type_fields(fall)["severity"] == "critical"
    stored = SimpleNamespace(type=PPE, type_detail="missing_gloves", model_id="x", severity="LOW")
    assert labeler.type_fields(stored)["severity"] == "low"  # stored value wins


# --------------------------------------------------------------------------
# Manifest reading
# --------------------------------------------------------------------------


def test_read_enabled_models_reads_rule_display_names(tmp_path):
    version_dir = tmp_path / "gloves" / "1.0.0"
    version_dir.mkdir(parents=True)
    (version_dir / "store_manifest.json").write_text(
        json.dumps(
            {
                "model_id": "gloves",
                "display_name": "Gloves",
                "rules": [
                    {"id": "a", "violation_type": "Missing_Gloves", "display_name": " Missing gloves ",
                     "min_confidence": 0.7},
                    {"id": "b", "violation_type": "missing_boots", "display_name": "   ",
                     "min_confidence": 0.7},
                    {"id": "c", "violation_type": "missing_mask", "min_confidence": 0.7},
                ],
            }
        )
    )
    info = read_enabled_models(tmp_path)["gloves"]
    assert info.rule_labels == (("missing_gloves", "Missing gloves"),)
    assert info.rule_label("missing_gloves") == "Missing gloves"
    assert info.rule_label("missing_boots") is None


# --------------------------------------------------------------------------
# Breakdowns
# --------------------------------------------------------------------------


def row(type_, detail, count):
    return SimpleNamespace(type=type_, type_detail=detail, count=count)


def test_type_options_group_by_family_and_drop_details_for_detail_free_families():
    rows = [
        row(PPE, "missing_vest", 10),
        row(PPE, "missing_gloves", 4),
        row(PPE, None, 2),
        row(FALL, None, 3),
        row(ZONE, "tank_critical_high", 1),
    ]
    options = build_type_options(rows, ViolationLabeler())
    assert [(o.type, o.label, o.count) for o in options] == [
        ("ppe_violation", "PPE Violation", 16),
        ("fall_detected", "Fall Detected", 3),
        ("zone_intrusion", "Zone Intrusion", 1),
    ]
    ppe = options[0]
    assert [(d.type_detail, d.label, d.count) for d in ppe.details] == [
        ("missing_vest", "Missing safety vest", 10),
        ("missing_gloves", "Missing gloves", 4),
        (None, "PPE Violation", 2),  # reachable: "no specific type"
    ]
    assert options[1].details == []  # Fall: no specific types at all
    assert options[2].details[0].label == "Tank level critically high"


def test_analytics_breaks_down_every_family_with_details():
    rows = [
        row(PPE, "missing_vest", 6),
        row(PPE, "missing_gloves", 2),
        row(FALL, None, 1),
        row(FALL, "possible_fall", 1),
    ]
    breakdown = build_type_breakdown(rows, 10, ViolationLabeler())
    assert [(b.type, b.type_detail, b.type_display, b.count, b.percentage) for b in breakdown] == [
        ("ppe_violation", "missing_vest", "PPE Violation · Missing safety vest", 6, 60.0),
        ("ppe_violation", "missing_gloves", "PPE Violation · Missing gloves", 2, 20.0),
        ("fall_detected", None, "Fall Detected", 1, 10.0),
        ("fall_detected", "possible_fall", "Fall Detected · Possible fall", 1, 10.0),
    ]
    assert (breakdown[1].type_label, breakdown[1].detail_label) == ("PPE Violation", "Missing gloves")
    assert (breakdown[2].type_label, breakdown[2].detail_label) == ("Fall Detected", None)


async def test_csv_export_has_specific_type_columns(monkeypatch):
    monkeypatch.setattr(
        "app.services.violation_labels.enabled_store_models",
        lambda: {"gloves_2": store("gloves_2", ("missing_gloves", "Missing gloves"))},
    )
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    violation = SimpleNamespace(
        id=uuid.uuid4(),
        type=PPE,
        type_detail="missing_gloves",
        model_id="gloves_2",
        model_version="1.0.0",
        camera_name="Cam 1",
        status=ViolationStatus.OPEN,
        confidence=0.81,
        timestamp=now,
        created_at=now,
        reviewed_by=None,
        reviewed_at=None,
        bounding_boxes=None,
    )
    body, mime, _ = await ExportService(db=None)._export_csv(
        [violation], now, now, True, True, False, False, False
    )
    assert mime == "text/csv"
    header, data = list(csv.reader(io.StringIO(body.decode())))
    record = dict(zip(header, data))
    assert header[:6] == ["id", "type", "type_detail", "type_label", "camera_name", "status"]
    assert record["type"] == "ppe_violation"
    assert record["type_detail"] == "missing_gloves"
    assert record["type_label"] == "PPE Violation · Missing gloves"
