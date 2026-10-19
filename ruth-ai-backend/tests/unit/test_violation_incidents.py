"""Batch A of the Violations page: severity, incidents, thumbnails, filters."""

import importlib.util
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.v1.violations import apply_violation_filters, camera_fields
from app.models import Violation, ViolationStatus
from app.models.enums import ViolationType
from app.services.frame_thumbnails import Box, boxes_in_frame, crop_rect, render_thumbnail
from app.services.incidents import group_incidents
from app.services.model_store.enabled import StoreModelInfo, read_enabled_models
from app.services.violation_severity import (
    BUILTIN_SEVERITY,
    resolve_severity,
    worst_severity,
)

REPO = Path(__file__).resolve().parents[3]
MANIFESTS = REPO / "ai" / "store_plugin" / "manifests"
MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "versions" / "2026_10_19_violation_severity.py"
)
T0 = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
CAM_A, CAM_B = uuid.uuid4(), uuid.uuid4()
PPE = ViolationType.PPE_VIOLATION


# --------------------------------------------------------------------------
# Severity
# --------------------------------------------------------------------------


def store(model_id, *severities):
    return StoreModelInfo(model_id=model_id, version="1", display_name=model_id, rule_severities=severities)


def test_severity_order_reported_then_manifest_then_builtin():
    models = {"vest": store("vest", ("missing_vest", "critical")), "other": store("other", ("missing_vest", "low"))}
    kw = dict(type_=PPE, type_detail="missing_vest", model_id="vest", store_models=models)
    assert resolve_severity(reported="LOW", **kw) == "low"  # model's own report wins
    assert resolve_severity(reported="bogus", **kw) == "critical"  # own manifest
    assert resolve_severity(**{**kw, "model_id": "gone"}) == "low"  # any manifest, sorted
    assert resolve_severity(type_=PPE, type_detail="missing_vest", model_id=None) == "high"  # family
    assert resolve_severity(type_=ViolationType.ZONE_INTRUSION, type_detail="tank_critical_high",
                            model_id="tank") == "critical"
    assert resolve_severity(type_=ViolationType.FALL_DETECTED, type_detail=None, model_id="fall") == "critical"
    assert resolve_severity(type_="something_new", type_detail=None, model_id=None) == "medium"
    assert worst_severity(["high", "critical", None, "low"]) == "critical"
    assert worst_severity([]) == "medium"


def test_manifests_carry_rule_severities(tmp_path):
    version_dir = tmp_path / "vest" / "1.0.0"
    version_dir.mkdir(parents=True)
    (version_dir / "store_manifest.json").write_text(json.dumps({
        "rules": [{"id": "a", "violation_type": "Missing_Vest", "severity": " Critical ", "min_confidence": 0.5}],
    }))
    assert read_enabled_models(tmp_path)["vest"].rule_severity("missing_vest") == "critical"


def test_migration_backfill_matches_shipped_manifests_and_builtins():
    """The migration inlines severities; they must equal the manifests'."""
    spec = importlib.util.spec_from_file_location("violation_severity_migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    shipped: dict[str, set[str]] = {}
    for path in MANIFESTS.glob("*.json"):
        for rule in json.loads(path.read_text())["rules"]:
            shipped.setdefault(rule["violation_type"], set()).add(rule["severity"])
    assert all(len(levels) == 1 for levels in shipped.values()), shipped  # no conflicts
    assert migration.MANIFEST_SEVERITY == {k: v.pop() for k, v in shipped.items()}
    assert {**migration.BUILTIN_DETAIL_SEVERITY, **migration.BUILTIN_FAMILY_SEVERITY} == BUILTIN_SEVERITY


# --------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------


def v(minutes, cam=CAM_A, detail="missing_gloves", status=ViolationStatus.OPEN, severity="high"):
    return SimpleNamespace(
        id=uuid.uuid4(), device_id=cam, type=PPE, type_detail=detail,
        timestamp=T0 + timedelta(minutes=minutes), status=status, severity=severity,
    )


GAP, CAP = timedelta(minutes=5), timedelta(minutes=60)


def test_repeats_within_the_gap_form_one_incident():
    rows = [v(0), v(1), v(4.5), v(9)]  # each within 5 min of the previous
    [incident] = group_incidents(rows, GAP, CAP)
    assert incident.count == 4
    assert (incident.first_at, incident.last_at) == (T0, T0 + timedelta(minutes=9))
    assert incident.latest is rows[-1]


def test_a_gap_over_the_window_starts_a_new_incident():
    incidents = group_incidents([v(0), v(2), v(8)], GAP, CAP)
    assert [i.count for i in incidents] == [1, 2]  # newest first


def test_the_span_cap_cuts_a_camera_that_fires_all_day():
    rows = [v(m) for m in range(0, 150, 2)]  # every 2 min for 2.5 h
    incidents = group_incidents(rows, GAP, CAP)
    spans = [(i.last_at - i.first_at) for i in incidents]
    assert len(incidents) == 3
    assert all(span <= CAP for span in spans)
    assert sum(i.count for i in incidents) == len(rows)


def test_different_camera_or_specific_type_never_merge():
    incidents = group_incidents([v(0), v(1, cam=CAM_B), v(2, detail="missing_vest"), v(3, detail=None)],
                                GAP, CAP)
    assert len(incidents) == 4


def test_counts_severity_and_order():
    rows = [v(0, severity="high"), v(1, status=ViolationStatus.REVIEWED, severity=None), v(2, severity="critical")]
    [incident] = group_incidents(rows, GAP, CAP)
    assert incident.count_with_status("open") == 2
    assert incident.severity(lambda row: "low") == "critical"
    older = group_incidents([v(-30, cam=CAM_B), *rows], GAP, CAP)
    assert older[0].last_at > older[1].last_at  # most recently active first
    assert older[0].key.endswith(str(rows[0].id))  # key = first member, stable as it grows


# --------------------------------------------------------------------------
# Thumbnails
# --------------------------------------------------------------------------


def test_crop_is_4_3_inside_the_frame_and_contains_the_box():
    box = Box(542, 497, 71, 58)  # a real stored box, 1280x720 frame
    left, top, right, bottom = crop_rect([box], 1280, 720)
    w, h = right - left, bottom - top
    assert abs(w / h - 4 / 3) < 0.02
    assert 0 <= left and right <= 1280 and 0 <= top and bottom <= 720
    assert left <= box.x and box.x + box.width <= right and top <= box.y and box.y + box.height <= bottom
    assert w >= 1280 * 0.3 - 1  # never a postage stamp


def test_crop_of_a_huge_box_or_no_box_is_the_largest_4_3():
    assert crop_rect([Box(0, 0, 1280, 720)], 1280, 720) == (160, 0, 1120, 720)  # centred on the box
    assert crop_rect([], 1280, 720) == (160, 0, 1120, 720)


def test_boxes_rescale_to_the_saved_frame_and_skip_bad_ones():
    boxes = boxes_in_frame(
        [{"x": 100, "y": 50, "width": 20, "height": 10, "frame_width": 640, "frame_height": 360},
         {"x": "?", "y": 0, "width": 1, "height": 1}, {"x": 0, "y": 0, "width": 0, "height": 5}],
        1280, 720,
    )
    assert boxes == [Box(200, 100, 40, 20)]


def test_render_thumbnail(tmp_path):
    from PIL import Image

    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (1280, 720), (30, 30, 30)).save(frame)
    out = render_thumbnail(frame, [{"x": 542, "y": 497, "width": 71, "height": 58}], tmp_path / "t" / "v.jpg")
    with Image.open(out) as thumb:
        assert thumb.size == (320, 240)
        # The box is drawn somewhere in red.
        assert any(px[0] > 200 and px[1] < 100 for px in thumb.getdata())
    assert not list((tmp_path / "t").glob("*.tmp"))


# --------------------------------------------------------------------------
# Filters and camera fields
# --------------------------------------------------------------------------


def sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_filters_cover_status_list_severity_and_area():
    q = sql(apply_violation_filters(
        select(Violation.id),
        statuses=[ViolationStatus.OPEN, ViolationStatus.REVIEWED],
        severities=["Critical", "high"],
        area="REFORMER1",
        type_detail="none",
    ))
    assert "violations.status IN ('OPEN', 'REVIEWED')" in q or "IN ('open', 'reviewed')" in q
    assert "violations.severity IN ('critical', 'high')" in q
    assert "devices.manway = 'REFORMER1'" in q
    assert "violations.type_detail IS NULL" in q


def test_unknown_severity_is_rejected():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        apply_violation_filters(select(Violation.id), severities=["urgent"])
    assert exc.value.status_code == 422


def test_camera_fields():
    device = SimpleNamespace(display_name=" REFORMER1_OUT_75081 ", manway="REFORMER1", in_out="OUT")
    assert camera_fields(device) == {
        "camera_display_name": "REFORMER1_OUT_75081", "camera_area": "REFORMER1", "camera_in_out": "OUT",
    }
    assert camera_fields(None)["camera_area"] is None
    assert camera_fields(SimpleNamespace(display_name="", manway=None, in_out=None))["camera_display_name"] is None
