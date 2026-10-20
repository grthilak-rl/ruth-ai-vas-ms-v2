"""Bulk evidence export: naming, selection, archive contents.

The parts that decide what the AI engineer actually receives, pinned
without a database: the filename contract, which image represents an
incident, and what ends up inside the ZIP.

The archive writer is deliberately pure and blocking, so it can be driven
straight from a test with a real temp tree and a real zipfile.
"""

import csv
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.false_positive_export import (
    EVIDENCE_INFERRED_FRAME,
    EVIDENCE_SCENE_SNAPSHOT,
    ExportItem,
    build_sidecar,
)
from app.services.violation_export import (
    CSV_COLUMNS,
    ExportOptions,
    Plan,
    PlannedItem,
    _annotate,
    finalize,
    image_name,
    open_archive,
    pick_one_per_incident,
    safe_name,
    write_chunk,
)

T0 = datetime(2026, 10, 20, 7, 8, 9, tzinfo=timezone.utc)


def _jpeg(width=64, height=48, colour=(10, 20, 30)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buf, format="JPEG")
    return buf.getvalue()


def _item(**over) -> ExportItem:
    base = dict(
        violation_id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        model_id="gloves_2",
        model_version="1.0.0",
        type="ppe_violation",
        type_detail="missing_gloves",
        severity="high",
        confidence=0.81,
        timestamp=T0,
        camera_name="75081",
        camera_display_name="Manway A",
        camera_area="manway-a",
        camera_in_out="IN",
        bounding_boxes=[
            {
                "x": 10,
                "y": 12,
                "width": 20,
                "height": 18,
                "label": "no-gloves",
                "confidence": 0.81,
                "frame_width": 64,
                "frame_height": 48,
            }
        ],
        frame_file="2026/10/20/11111111-2222-3333-4444-555555555555.jpg",
        status="open",
    )
    base.update(over)
    return ExportItem(**base)


def _plan(frame_path=None, snapshot_id=None, **over) -> PlannedItem:
    item_over = {k: over.pop(k) for k in list(over) if k in ExportItem.__annotations__}
    return PlannedItem(
        item=_item(**item_over),
        frame_path=frame_path,
        snapshot_id=snapshot_id,
        status=over.pop("status_", "open"),
        reviewed_by=over.pop("reviewed_by", None),
        reviewed_at=over.pop("reviewed_at", None),
        dismiss_reason=over.pop("dismiss_reason", None),
        type_label=over.pop("type_label", "PPE Violation"),
    )


# ---------- filenames ----------

def test_image_name_follows_the_agreed_contract():
    plan = _plan()
    assert image_name(plan) == (
        "75081_missing_gloves_20261020T070809Z_"
        "11111111-2222-3333-4444-555555555555.jpg"
    )


def test_image_name_falls_back_to_the_type_family_when_detail_is_null():
    """type_detail is nullable; the name must not get a double underscore."""
    plan = _plan(type_detail=None)
    assert "__" not in image_name(plan)
    assert "_ppe_violation_" in image_name(plan)


def test_image_name_is_utc_regardless_of_the_timestamp_offset():
    plan = _plan(timestamp=datetime(2026, 10, 20, 12, 38, 9, tzinfo=timezone(__import__("datetime").timedelta(hours=5, minutes=30))))
    assert "20261020T070809Z" in image_name(plan)


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Separators become underscores, then leading dots/underscores
        # are stripped, so traversal cannot survive even in pieces.
        ("../../etc/passwd", "etc_passwd"),
        ("cam/01", "cam_01"),
        ("a b", "a_b"),
        ("", "unknown"),
        (None, "unknown"),
        ("...", "unknown"),
    ],
)
def test_safe_name_cannot_produce_a_path(raw, expected):
    out = safe_name(raw)
    assert out == expected
    assert "/" not in out


def test_image_name_survives_a_hostile_camera_name():
    plan = _plan(camera_name="../../evil")
    name = image_name(plan)
    assert "/" not in name
    assert ".." not in name
    assert name.startswith("evil_")


# ---------- one per incident ----------

def test_one_per_incident_prefers_a_frame_over_higher_confidence_snapshot():
    """A snapshot's boxes do not line up, so it is the worse example."""
    with_frame = _plan(frame_path=Path("/frames/a.jpg"), confidence=0.55)
    snapshot_only = _plan(snapshot_id="s1", confidence=0.99)
    picked = pick_one_per_incident(
        [snapshot_only, with_frame], lambda p: "incident-1"
    )
    assert picked == [with_frame]


def test_one_per_incident_takes_highest_confidence_among_frames():
    low = _plan(frame_path=Path("/frames/a.jpg"), confidence=0.40)
    high = _plan(frame_path=Path("/frames/b.jpg"), confidence=0.92)
    picked = pick_one_per_incident([low, high], lambda p: "incident-1")
    assert picked == [high]


def test_one_per_incident_returns_one_per_group():
    a1 = _plan(frame_path=Path("/f/a1.jpg"), confidence=0.5)
    a2 = _plan(frame_path=Path("/f/a2.jpg"), confidence=0.6)
    b1 = _plan(frame_path=Path("/f/b1.jpg"), confidence=0.7)
    keys = {id(a1): "A", id(a2): "A", id(b1): "B"}
    picked = pick_one_per_incident([a1, a2, b1], lambda p: keys[id(p)])
    assert len(picked) == 2
    assert a2 in picked and b1 in picked


def test_one_per_incident_skips_items_with_no_incident():
    orphan = _plan(frame_path=Path("/f/a.jpg"))
    assert pick_one_per_incident([orphan], lambda p: None) == []


def test_one_per_incident_handles_null_confidence():
    a = _plan(frame_path=Path("/f/a.jpg"), confidence=None)
    b = _plan(frame_path=Path("/f/b.jpg"), confidence=0.1)
    assert pick_one_per_incident([a, b], lambda p: "i") == [b]


# ---------- size estimate ----------

def test_estimate_counts_annotated_copies_and_snapshots():
    frames = [_plan(frame_path=Path("/f/x.jpg")) for _ in range(4)]
    snaps = [_plan(snapshot_id="s") for _ in range(2)]
    plan = Plan(items=frames + snaps, matched=6, no_frame=2)

    clean = plan.estimate_bytes(annotated=False, include_snapshots=False)
    with_snaps = plan.estimate_bytes(annotated=False, include_snapshots=True)
    with_both = plan.estimate_bytes(annotated=True, include_snapshots=True)

    # Snapshots are the expensive ones, and annotating only copies frames.
    assert with_snaps > clean
    assert with_both - with_snaps == 4 * 253_000
    assert with_snaps - clean == 2 * 810_000


# ---------- the sidecar ----------

def test_sidecar_carries_status_source_and_box_applicability():
    sidecar = build_sidecar(
        _item(),
        image_name="x.jpg",
        width=64,
        height=48,
        evidence_source=EVIDENCE_SCENE_SNAPSHOT,
        boxes_apply_to_image=False,
    )
    assert sidecar["status"] == "open"
    assert sidecar["evidence_source"] == EVIDENCE_SCENE_SNAPSHOT
    assert sidecar["boxes_apply_to_image"] is False
    # The metadata the AI engineer asked for, all present.
    assert sidecar["model_id"] == "gloves_2"
    assert sidecar["model_version"] == "1.0.0"
    assert sidecar["type_detail"] == "missing_gloves"
    assert sidecar["severity"] == "high"
    assert sidecar["confidence"] == 0.81
    assert sidecar["camera"]["area"] == "manway-a"
    assert sidecar["frame"] == {"width": 64, "height": 48}
    assert sidecar["boxes"][0]["x"] == 10


def test_sidecar_defaults_to_the_inferred_frame():
    sidecar = build_sidecar(_item(), image_name="x.jpg", width=1, height=1)
    assert sidecar["evidence_source"] == EVIDENCE_INFERRED_FRAME
    assert sidecar["boxes_apply_to_image"] is True


# ---------- annotation ----------

def test_annotate_returns_a_readable_jpeg():
    from PIL import Image

    out = _annotate(_jpeg(), _item().bounding_boxes)
    assert out is not None
    with Image.open(io.BytesIO(out)) as image:
        assert image.size == (64, 48)


def test_annotate_differs_from_the_clean_frame():
    clean = _jpeg()
    drawn = _annotate(clean, _item().bounding_boxes)
    assert drawn != clean, "boxes should actually be drawn"


def test_annotate_survives_a_corrupt_image():
    assert _annotate(b"not a jpeg", _item().bounding_boxes) is None


def test_annotate_ignores_malformed_boxes():
    out = _annotate(_jpeg(), [{"x": "bad"}, None, {"no": "geometry"}])
    assert out is not None


# ---------- the archive ----------

def _read_archive(path: Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(path, "r")


def test_archive_holds_image_sidecar_and_annotated_copy(tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(_jpeg())
    plan = _plan(frame_path=frame)
    rows: list[list] = []

    zip_path = tmp_path / "out.zip"
    archive = open_archive(zip_path)
    counts = write_chunk(
        archive,
        [(plan, None, EVIDENCE_INFERRED_FRAME)],
        annotated=True,
        csv_rows=rows,
    )
    finalize(archive, rows, {"export_id": "x"})
    archive.close()

    assert counts == {"images": 1, "no_frame": 0, "skipped": 0}
    name = image_name(plan)
    with _read_archive(zip_path) as z:
        names = z.namelist()
        assert f"images/{name}" in names
        assert f"images/{name[:-4]}.json" in names
        assert f"annotated/{name}" in names
        assert "index.csv" in names
        assert "manifest.json" in names

        # The clean image is byte-identical to the frame the model saw.
        assert z.read(f"images/{name}") == frame.read_bytes()
        assert z.read(f"annotated/{name}") != frame.read_bytes()

        sidecar = json.loads(z.read(f"images/{name[:-4]}.json"))
        assert sidecar["evidence_source"] == EVIDENCE_INFERRED_FRAME
        assert sidecar["boxes_apply_to_image"] is True
        assert sidecar["annotated_image"] == f"annotated/{name}"


def test_snapshot_fallback_is_marked_and_never_annotated(tmp_path):
    plan = _plan(snapshot_id="snap-1")
    rows: list[list] = []
    zip_path = tmp_path / "out.zip"
    archive = open_archive(zip_path)
    counts = write_chunk(
        archive,
        [(plan, _jpeg(80, 60), EVIDENCE_SCENE_SNAPSHOT)],
        annotated=True,
        csv_rows=rows,
    )
    archive.close()

    assert counts["images"] == 1
    name = image_name(plan)
    with _read_archive(zip_path) as z:
        assert f"images/{name}" in z.namelist()
        assert not [n for n in z.namelist() if n.startswith("annotated/")], (
            "a snapshot must never be annotated: its boxes do not line up"
        )
        sidecar = json.loads(z.read(f"images/{name[:-4]}.json"))
        assert sidecar["evidence_source"] == EVIDENCE_SCENE_SNAPSHOT
        assert sidecar["boxes_apply_to_image"] is False
        assert sidecar["annotated_image"] is None
        # Boxes are still shipped; they just do not apply to THIS image.
        assert sidecar["boxes"]


def test_violation_with_no_image_is_counted_not_dropped_silently(tmp_path):
    plan = _plan()  # no frame on disk, no snapshot bytes
    rows: list[list] = []
    archive = open_archive(tmp_path / "out.zip")
    counts = write_chunk(
        archive, [(plan, None, EVIDENCE_SCENE_SNAPSHOT)], annotated=False, csv_rows=rows
    )
    archive.close()
    assert counts["no_frame"] == 1
    assert counts["images"] == 0
    assert rows == []


def test_unreadable_frame_is_skipped_not_fatal(tmp_path):
    missing = tmp_path / "gone.jpg"
    plan = _plan(frame_path=missing)
    rows: list[list] = []
    archive = open_archive(tmp_path / "out.zip")
    counts = write_chunk(
        archive, [(plan, None, EVIDENCE_INFERRED_FRAME)], annotated=False, csv_rows=rows
    )
    archive.close()
    assert counts["skipped"] == 1


def test_annotated_omitted_when_there_are_no_boxes(tmp_path):
    frame = tmp_path / "f.jpg"
    frame.write_bytes(_jpeg())
    plan = _plan(frame_path=frame, bounding_boxes=[])
    rows: list[list] = []
    archive = open_archive(tmp_path / "out.zip")
    write_chunk(
        archive, [(plan, None, EVIDENCE_INFERRED_FRAME)], annotated=True, csv_rows=rows
    )
    archive.close()
    with _read_archive(tmp_path / "out.zip") as z:
        assert not [n for n in z.namelist() if n.startswith("annotated/")]


def test_index_csv_matches_the_declared_columns(tmp_path):
    frame = tmp_path / "f.jpg"
    frame.write_bytes(_jpeg())
    plan = _plan(
        frame_path=frame,
        status_="dismissed",
        dismiss_reason="ppe_actually_worn",
        reviewed_by="admin",
        reviewed_at=T0,
    )
    rows: list[list] = []
    zip_path = tmp_path / "out.zip"
    archive = open_archive(zip_path)
    write_chunk(
        archive, [(plan, None, EVIDENCE_INFERRED_FRAME)], annotated=False, csv_rows=rows
    )
    finalize(archive, rows, {"export_id": "x"})
    archive.close()

    with _read_archive(zip_path) as z:
        parsed = list(csv.DictReader(io.StringIO(z.read("index.csv").decode())))

    assert list(parsed[0]) == CSV_COLUMNS
    row = parsed[0]
    # Aligned with the analytics CSV export.
    assert row["id"] == str(plan.item.violation_id)
    assert row["type"] == "ppe_violation"
    assert row["type_detail"] == "missing_gloves"
    assert row["type_label"] == "PPE Violation"
    assert row["camera_name"] == "75081"
    assert row["model_id"] == "gloves_2"
    # The three the analytics export lacks.
    assert row["severity"] == "high"
    assert row["area"] == "manway-a"
    assert row["dismiss_reason"] == "ppe_actually_worn"
    # Archive-local.
    assert row["image"] == f"images/{image_name(plan)}"
    assert row["evidence_source"] == EVIDENCE_INFERRED_FRAME
    assert row["boxes_apply_to_image"] == "true"
    assert row["frame_width"] == "64"
    assert row["status"] == "dismissed"


def test_images_are_stored_not_deflated(tmp_path):
    """JPEGs do not compress; deflating them costs time for ~0% gain."""
    frame = tmp_path / "f.jpg"
    frame.write_bytes(_jpeg(400, 300))
    rows: list[list] = []
    zip_path = tmp_path / "out.zip"
    archive = open_archive(zip_path)
    write_chunk(
        archive, [(frame_plan := _plan(frame_path=frame), None, EVIDENCE_INFERRED_FRAME)],
        annotated=False, csv_rows=rows,
    )
    finalize(archive, rows, {"export_id": "x"})
    archive.close()

    with _read_archive(zip_path) as z:
        image_info = z.getinfo(f"images/{image_name(frame_plan)}")
        csv_info = z.getinfo("index.csv")
    assert image_info.compress_type == zipfile.ZIP_STORED
    # Text still compresses, so it is worth deflating.
    assert csv_info.compress_type == zipfile.ZIP_DEFLATED


def test_manifest_records_what_was_requested(tmp_path):
    rows: list[list] = []
    zip_path = tmp_path / "out.zip"
    archive = open_archive(zip_path)
    manifest = {
        "request": ExportOptions(
            scope="one_per_incident", annotated=True
        ).as_dict(),
        "violations_in_export": 0,
    }
    finalize(archive, rows, manifest)
    archive.close()
    with _read_archive(zip_path) as z:
        got = json.loads(z.read("manifest.json"))
    assert got["request"]["scope"] == "one_per_incident"
    assert got["request"]["annotated"] is True


def test_archive_is_zip64_capable(tmp_path):
    """A 1.5GB export must not hit the 4GB/65535-entry ZIP limits."""
    archive = open_archive(tmp_path / "out.zip")
    try:
        assert archive._allowZip64 is True
    finally:
        archive.close()
