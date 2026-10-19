"""Batch B of the Violations page: dismiss reasons + labelling export, bulk
actions, the summary strip, and the background clip-status sync."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api.v1 import violations as violations_api
from app.models import ViolationStatus
from app.models.dismiss_reasons import (
    FALSE_ALARM_REASONS,
    YOLO_BACKGROUND_REASONS,
    DismissReason,
)
from app.models.enums import ViolationType
from app.schemas import ViolationBulkRequest
from app.services import clip_status_sync as sync_mod
from app.services.false_positive_export import ExportItem, export_false_positives, is_false_alarm
from app.services.incidents import group_incidents
from app.services.violation_labels import ViolationLabeler
from app.services.violation_service import (
    ViolationService,
    ViolationStateError,
    ViolationTerminalStateError,
)

T0 = datetime(2026, 10, 19, 9, 30, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Reasons
# --------------------------------------------------------------------------


def test_reason_sets():
    assert DismissReason.DUPLICATE not in FALSE_ALARM_REASONS
    assert YOLO_BACKGROUND_REASONS == {DismissReason.OBJECT, DismissReason.PPE_WORN}
    assert is_false_alarm("wrong_person") and not is_false_alarm("duplicate")
    assert not is_false_alarm("nonsense") and not is_false_alarm(None)


def test_bulk_request_rules():
    vid = uuid.uuid4()
    with pytest.raises(ValidationError, match="dismiss_reason is required"):
        ViolationBulkRequest(ids=[vid], action="dismiss")
    with pytest.raises(ValidationError, match="note is required"):
        ViolationBulkRequest(ids=[vid], action="dismiss", dismiss_reason="other_false_alarm", note="  ")
    with pytest.raises(ValidationError):
        ViolationBulkRequest(ids=[], action="review")
    with pytest.raises(ValidationError):
        ViolationBulkRequest(ids=[vid], action="dismiss", dismiss_reason="because")
    assert ViolationBulkRequest(ids=[vid], action="review").dismiss_reason is None
    ok = ViolationBulkRequest(ids=[vid], action="dismiss", dismiss_reason="other_false_alarm", note="glare")
    assert ok.dismiss_reason is DismissReason.OTHER_FALSE_ALARM


# --------------------------------------------------------------------------
# Transitions
# --------------------------------------------------------------------------


def v(status=ViolationStatus.OPEN, **over):
    base = dict(
        id=uuid.uuid4(), status=status, reviewed_by=None, reviewed_at=None,
        resolution_notes=None, dismiss_reason=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_dismiss_records_reason_and_note_and_reopen_clears_it():
    service = ViolationService(db=None)
    violation = v()
    service.apply_transition(violation, ViolationStatus.DISMISSED, dismiss_reason="ppe_worn",
                             resolution_notes="gloves are grey")
    assert (violation.status, violation.dismiss_reason, violation.resolution_notes) == (
        ViolationStatus.DISMISSED, "ppe_worn", "gloves are grey",
    )
    service.apply_transition(violation, ViolationStatus.OPEN)
    assert violation.dismiss_reason is None


def test_invalid_transitions_raise():
    service = ViolationService(db=None)
    with pytest.raises(ViolationStateError):
        service.apply_transition(v(ViolationStatus.DISMISSED), ViolationStatus.REVIEWED)
    with pytest.raises(ViolationTerminalStateError):
        service.apply_transition(v(ViolationStatus.RESOLVED), ViolationStatus.DISMISSED)


# --------------------------------------------------------------------------
# Labelling export
# --------------------------------------------------------------------------


def make_frame(root: Path, rel: str = "2026/10/19/f.jpg") -> str:
    from PIL import Image

    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1280, 720), (40, 40, 40)).save(path)
    return rel


def item(frame_file, **over) -> ExportItem:
    base = dict(
        violation_id=uuid.uuid4(), model_id="gloves_2", model_version="1.0.0",
        type="ppe_violation", type_detail="missing_gloves", severity="high", confidence=0.81,
        timestamp=T0, camera_name="75084", camera_display_name="REFORMER2_OUT_75084",
        camera_area="REFORMER2", camera_in_out="OUT",
        bounding_boxes=[{"x": 542, "y": 497, "width": 71, "height": 58, "label": "missing_gloves",
                         "confidence": 0.81, "frame_width": 1280, "frame_height": 720}],
        frame_file=frame_file, group_key="cam:missing_gloves",
    )
    base.update(over)
    return ExportItem(**base)


@pytest.mark.parametrize(
    "reason, expect_txt",
    [("object", True), ("ppe_worn", True), ("wrong_person", False), ("other_false_alarm", False)],
)
def test_export_writes_frame_json_and_yolo_only_for_background(tmp_path, reason, expect_txt):
    frames, labelling = tmp_path / "frames", tmp_path / "labelling"
    it = item(make_frame(frames))
    result = export_false_positives([it], reason, "note", frame_root=frames, labelling_root=labelling,
                                    dismissed_by="op1")
    assert result.exported == 1

    out = labelling / "false_positives" / "gloves_2" / "2026-10-19"
    stem = str(it.violation_id)
    assert (out / f"{stem}.jpg").read_bytes() == (frames / it.frame_file).read_bytes()
    assert (out / f"{stem}.txt").exists() is expect_txt
    if expect_txt:
        assert (out / f"{stem}.txt").read_text() == ""  # background: no objects
    meta = json.loads((out / f"{stem}.json").read_text())
    assert meta["image"] == f"{stem}.jpg"
    assert meta["frame"] == {"width": 1280, "height": 720}
    assert meta["boxes"][0]["x"] == 542 and meta["boxes"][0]["label"] == "missing_gloves"
    assert meta["dismiss_reason"] == reason and meta["yolo_background"] is expect_txt
    assert meta["model_id"] == "gloves_2" and meta["camera"]["area"] == "REFORMER2"
    assert not list(out.glob(".*.tmp"))


def test_redismissing_with_a_non_background_reason_removes_the_old_label(tmp_path):
    frames, labelling = tmp_path / "frames", tmp_path / "labelling"
    it = item(make_frame(frames))
    export_false_positives([it], "object", None, frame_root=frames, labelling_root=labelling)
    export_false_positives([it], "wrong_person", None, frame_root=frames, labelling_root=labelling)
    assert not list(labelling.rglob("*.txt"))


def test_export_skips_missing_frames_caps_groups_and_ignores_duplicates(tmp_path):
    frames, labelling = tmp_path / "frames", tmp_path / "labelling"
    rel = make_frame(frames)
    items = [item(rel) for _ in range(53)] + [item(None), item("../../etc/passwd")]
    result = export_false_positives(items, "object", None, frame_root=frames, labelling_root=labelling)
    assert (result.exported, result.capped, result.no_frame, result.failed) == (50, 3, 2, 0)
    assert export_false_positives(items, "duplicate", None, frame_root=frames,
                                  labelling_root=labelling).exported == 0


def test_model_id_cannot_escape_the_labelling_root(tmp_path):
    frames, labelling = tmp_path / "frames", tmp_path / "labelling"
    export_false_positives([item(make_frame(frames), model_id="../../x")], "object", None,
                           frame_root=frames, labelling_root=labelling)
    written = list(labelling.rglob("*.jpg"))
    assert len(written) == 1 and written[0].is_relative_to(labelling)


# --------------------------------------------------------------------------
# Bulk endpoint (against fakes)
# --------------------------------------------------------------------------


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


async def test_bulk_updates_valid_rows_skips_the_rest_and_exports(monkeypatch):
    open_a, open_b = v(), v()
    reviewed, resolved = v(ViolationStatus.REVIEWED), v(ViolationStatus.RESOLVED)
    missing = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=FakeResult([open_a, open_b, reviewed, resolved]))
    db.commit = AsyncMock()
    exported = AsyncMock(return_value=violations_api.LabellingExport(exported=2))
    monkeypatch.setattr(violations_api, "export_dismissed_false_alarms", exported)

    req = ViolationBulkRequest(
        ids=[open_a.id, open_b.id, open_a.id, reviewed.id, resolved.id, missing],
        action="dismiss", dismiss_reason="ppe_worn", reviewed_by="op1",
    )
    response = await violations_api.bulk_update_violations(req, ViolationService(db=None), db)

    assert response.updated == [open_a.id, open_b.id, reviewed.id]  # reviewed -> dismissed is valid
    assert {(s.id, s.reason) for s in response.skipped} == {
        (resolved.id, "terminal_state"), (missing, "not_found"),
    }
    assert open_a.dismiss_reason == "ppe_worn"
    db.commit.assert_awaited()
    assert exported.await_args.args[1] == [open_a, open_b, reviewed]
    assert response.labelling.exported == 2


async def test_bulk_review_does_not_export(monkeypatch):
    row = v()
    db = MagicMock()
    db.execute = AsyncMock(return_value=FakeResult([row]))
    db.commit = AsyncMock()
    exported = AsyncMock()
    monkeypatch.setattr(violations_api, "export_dismissed_false_alarms", exported)
    response = await violations_api.bulk_update_violations(
        ViolationBulkRequest(ids=[row.id], action="review"), ViolationService(db=None), db
    )
    assert response.updated == [row.id] and row.status == ViolationStatus.REVIEWED
    assert response.labelling is None and not exported.await_count


# --------------------------------------------------------------------------
# Summary strip
# --------------------------------------------------------------------------


async def test_summary_counts_across_all_incidents():
    cam_a, cam_b = uuid.uuid4(), uuid.uuid4()

    def row(minutes, cam, severity, status=ViolationStatus.OPEN):
        return SimpleNamespace(
            id=uuid.uuid4(), device_id=cam, type=ViolationType.PPE_VIOLATION, type_detail="missing_vest",
            timestamp=T0 + timedelta(minutes=minutes), status=status, severity=severity, model_id="m",
        )

    rows = [row(0, cam_a, "critical"), row(1, cam_a, "critical"), row(30, cam_a, "high"),
            row(0, cam_b, "high", ViolationStatus.REVIEWED)]
    incidents = group_incidents(rows, timedelta(minutes=5), timedelta(minutes=60))
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: [(cam_a, "REFORMER1"), (cam_b, " ")]))

    summary = await violations_api.summarize_incidents(db, rows, incidents, ViolationLabeler())
    assert summary.open_violations == 3
    assert summary.violations_by_severity.critical == 2 and summary.violations_by_severity.high == 2
    assert summary.incidents_by_severity.critical == 1 and summary.incidents_by_severity.high == 2
    assert summary.cameras == 2
    assert (summary.top_area, summary.top_area_violations) == ("REFORMER1", 3)


# --------------------------------------------------------------------------
# Clip status sync
# --------------------------------------------------------------------------


def test_pending_clips_query_is_bounded_and_recent_first():
    q = str(sync_mod.pending_clips_query(50, timedelta(hours=48), T0).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "evidence.evidence_type = 'BOOKMARK'" in q or "evidence.evidence_type = 'bookmark'" in q
    assert "IN ('PENDING', 'PROCESSING')" in q or "IN ('pending', 'processing')" in q
    assert "evidence.requested_at >=" in q
    assert "ORDER BY evidence.requested_at DESC" in q and "LIMIT 50" in q


async def test_run_once_syncs_each_clip_and_survives_failures(monkeypatch):
    from app.models import EvidenceStatus

    clips = [SimpleNamespace(id=i, status=EvidenceStatus.PROCESSING) for i in range(3)]

    class Session:
        commit = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, _stmt):
            return FakeResult(clips)

    session = Session()

    class FakeEvidenceService:
        def __init__(self, vas, db):
            pass

        async def sync_evidence_status(self, clip):
            if clip.id == 0:
                clip.status = EvidenceStatus.READY
            elif clip.id == 1:
                raise RuntimeError("VAS timeout")
            else:
                clip.status = EvidenceStatus.FAILED

    monkeypatch.setattr(sync_mod, "get_session_factory", lambda: (lambda: session))
    monkeypatch.setattr(sync_mod, "get_vas_client_optional", lambda: object())
    monkeypatch.setattr(sync_mod, "EvidenceService", FakeEvidenceService)

    counts = await sync_mod.ClipStatusSync().run_once()
    assert (counts.checked, counts.ready, counts.failed, counts.errors) == (3, 1, 1, 1)
    session.commit.assert_awaited()


async def test_run_once_is_a_no_op_without_vas(monkeypatch):
    monkeypatch.setattr(sync_mod, "get_vas_client_optional", lambda: None)
    assert (await sync_mod.ClipStatusSync().run_once()).checked == 0
