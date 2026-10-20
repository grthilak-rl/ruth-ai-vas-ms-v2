"""Bulk download of violation evidence for the AI engineer.

What the model was given, in bulk, with enough metadata to become a dataset:
the inferred frame per violation, a JSON sidecar each, optional annotated
copies, and one CSV index. Built as a background job because a realistic
request is hundreds of megabytes (measured: 1.48 GB for every violation on
site to date) and thousands of files.

Three decisions worth knowing before reading the code:

* **Frames, not snapshots, by default.** A snapshot is a later capture of a
  moved scene, it is ~810KB against a frame's ~253KB, and it has to be
  pulled from VAS one HTTP request at a time — through the single event loop
  that every camera's frame fetch shares (BL-12). So the fallback is opt-in,
  rate-limited, and the sidecar says which image you got.
* **Boxes are only drawn on frames.** They are in the pixel space of the
  frame the model inferred, so on a snapshot they would point at the wrong
  thing. ``boxes_apply_to_image`` in the sidecar records this per image, and
  ``annotated/`` only ever contains frames.
* **The archive is stored, not deflated.** JPEGs do not compress: measured
  on 60 real frames, deflate produced 100.1% of the original size and took
  2.5x as long. Only the JSON and CSV are deflated.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.core.logging import get_logger
from app.services.false_positive_export import (
    EVIDENCE_INFERRED_FRAME,
    ExportItem,
    build_sidecar,
)

logger = get_logger(__name__)

#: Violations written into the archive between progress updates. Small
#: enough that the UI's bar moves, large enough that the DB is not the
#: bottleneck.
CHUNK = 50

#: index.csv columns. The first block matches the analytics CSV export
#: (export_service._export_csv) so the two files can be read by the same
#: script; then the three fields that export lacks and this one needs, then
#: the columns that only mean something inside an archive.
CSV_COLUMNS = [
    "id",
    "type",
    "type_detail",
    "type_label",
    "camera_name",
    "status",
    "confidence_raw",
    "timestamp",
    "reviewed_by",
    "reviewed_at",
    "bounding_boxes",
    "model_id",
    "model_version",
    # Present on the Violations page but missing from the analytics export.
    "severity",
    "area",
    "dismiss_reason",
    # Archive-local.
    "image",
    "annotated_image",
    "evidence_source",
    "boxes_apply_to_image",
    "frame_width",
    "frame_height",
]


@dataclass
class ExportOptions:
    """The request, as the operator made it."""

    #: "all" or "one_per_incident"
    scope: str = "all"
    annotated: bool = False
    include_snapshots: bool = False
    #: Incident keys from the page's selection; None means "use the filters".
    incident_ids: list[str] | None = None
    #: Echoed into the manifest so an archive explains itself.
    filters: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "scope": self.scope,
            "annotated": self.annotated,
            "include_snapshots": self.include_snapshots,
            "incident_ids": self.incident_ids,
            "filters": self.filters,
        }


@dataclass
class PlannedItem:
    """One violation resolved to the image that will represent it."""

    item: ExportItem
    #: Absolute path of the inferred frame, when there is one.
    frame_path: Path | None
    #: VAS snapshot id, used only when there is no frame and the fallback is on.
    snapshot_id: str | None
    status: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    dismiss_reason: str | None
    type_label: str | None

    @property
    def has_frame(self) -> bool:
        return self.frame_path is not None


@dataclass
class Plan:
    items: list[PlannedItem]
    #: Violations matching the filters, before the one-per-incident cut.
    matched: int
    #: Of `items`, how many have no inferred frame.
    no_frame: int

    @property
    def total(self) -> int:
        return len(self.items)

    def estimate_bytes(self, *, annotated: bool, include_snapshots: bool) -> int:
        """Rough archive size. Means measured on site: frames 253KB,
        snapshots 810KB, sidecars ~1.5KB."""
        frames = sum(1 for p in self.items if p.has_frame)
        snaps = (self.no_frame if include_snapshots else 0)
        total = frames * 253_000 + snaps * 810_000 + self.total * 1_500
        if annotated:
            total += frames * 253_000
        return total


def safe_name(value: str | None, fallback: str = "unknown") -> str:
    """A filename component that cannot contain a path or surprise a shell."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "").strip("._")
    return cleaned or fallback


def image_name(plan: PlannedItem) -> str:
    """<camera>_<type_detail>_<timestamp>_<violation_id>.jpg

    ``type_detail`` is nullable in the schema, so it falls back to the type
    family rather than leaving a double underscore in the name.
    """
    stamp = plan.item.timestamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    detail = plan.item.type_detail or plan.item.type
    return (
        f"{safe_name(plan.item.camera_name, 'camera')}"
        f"_{safe_name(detail, 'violation')}"
        f"_{stamp}_{plan.item.violation_id}.jpg"
    )


def pick_one_per_incident(plans: Iterable[PlannedItem], incident_key) -> list[PlannedItem]:
    """Highest-confidence member per incident, preferring one with a frame.

    An incident is mostly near-identical frames, so one good example is what
    a dataset wants. "Preferring a frame" matters because the alternative is
    a snapshot whose boxes do not line up — a worse example even at higher
    confidence.
    """
    best: dict[str, PlannedItem] = {}
    for plan in plans:
        key = incident_key(plan)
        if key is None:
            continue
        current = best.get(key)
        if current is None:
            best[key] = plan
            continue
        # A frame beats no frame; within the same kind, confidence decides.
        rank = (plan.has_frame, plan.item.confidence or 0.0)
        current_rank = (current.has_frame, current.item.confidence or 0.0)
        if rank > current_rank:
            best[key] = plan
    return list(best.values())


# ---------------------------------------------------------------------------
# Archive writing. Blocking; every function here runs in a worker thread.
# ---------------------------------------------------------------------------


def _annotate(frame_bytes: bytes, boxes: list | None) -> bytes | None:
    """Draw the model's boxes on a copy of the frame.

    Returns None if the image cannot be read, so a corrupt frame costs one
    annotated copy rather than the whole export.
    """
    try:
        from PIL import Image, ImageDraw

        with Image.open(io.BytesIO(frame_bytes)) as image:
            canvas = image.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        for box in boxes or []:
            if not isinstance(box, dict):
                continue
            try:
                x, y = int(box["x"]), int(box["y"])
                w, h = int(box["width"]), int(box["height"])
            except (KeyError, TypeError, ValueError):
                continue
            draw.rectangle([x, y, x + w, y + h], outline=(255, 64, 64), width=3)
            label = str(box.get("label") or "")
            confidence = box.get("confidence")
            if confidence is not None:
                label = f"{label} {float(confidence):.2f}".strip()
            if label:
                # Above the box, or inside it when the box touches the top.
                ty = y - 14 if y >= 14 else y + 2
                draw.text((x + 2, ty), label, fill=(255, 64, 64))
        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=90)
        return out.getvalue()
    except Exception as e:  # noqa: BLE001 - one bad image must not fail the job
        logger.warning("Could not annotate frame", error=str(e))
        return None


def _frame_dimensions(frame_bytes: bytes, boxes: list | None) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(frame_bytes)) as image:
            return image.size
    except Exception:  # noqa: BLE001 - boxes may carry it
        for box in boxes or []:
            if isinstance(box, dict) and box.get("frame_width") and box.get("frame_height"):
                return int(box["frame_width"]), int(box["frame_height"])
        return None, None


def write_chunk(
    archive: zipfile.ZipFile,
    chunk: list[tuple[PlannedItem, bytes | None, str]],
    *,
    annotated: bool,
    csv_rows: list[list],
) -> dict:
    """Add one batch of violations to an open archive.

    `chunk` carries the image bytes already in hand: frames are read here,
    snapshots were fetched on the async side because they come from VAS.
    """
    counts = {"images": 0, "no_frame": 0, "skipped": 0}
    for plan, fetched, source in chunk:
        data = fetched
        if data is None and plan.frame_path is not None:
            try:
                data = plan.frame_path.read_bytes()
            except OSError as e:
                logger.warning(
                    "Export could not read frame",
                    violation_id=str(plan.item.violation_id),
                    error=str(e),
                )
                counts["skipped"] += 1
                continue
        if data is None:
            # No frame, and either the fallback is off or its fetch failed.
            counts["no_frame"] += 1
            continue

        name = image_name(plan)
        is_frame = source == EVIDENCE_INFERRED_FRAME
        width, height = _frame_dimensions(data, plan.item.bounding_boxes)

        archive.writestr(f"images/{name}", data, compress_type=zipfile.ZIP_STORED)

        annotated_name = ""
        if annotated and is_frame and plan.item.bounding_boxes:
            drawn = _annotate(data, plan.item.bounding_boxes)
            if drawn is not None:
                annotated_name = name
                archive.writestr(
                    f"annotated/{name}", drawn, compress_type=zipfile.ZIP_STORED
                )

        sidecar = build_sidecar(
            plan.item,
            image_name=name,
            width=width,
            height=height,
            evidence_source=source,
            boxes_apply_to_image=is_frame,
            extra={
                "dismiss_reason": plan.dismiss_reason,
                "reviewed_by": plan.reviewed_by,
                "reviewed_at": plan.reviewed_at.isoformat() if plan.reviewed_at else None,
                "annotated_image": f"annotated/{annotated_name}" if annotated_name else None,
            },
        )
        archive.writestr(
            f"images/{name[:-4]}.json",
            json.dumps(sidecar, indent=2, default=str),
            compress_type=zipfile.ZIP_DEFLATED,
        )

        csv_rows.append(
            [
                str(plan.item.violation_id),
                plan.item.type,
                plan.item.type_detail or "",
                plan.type_label or "",
                plan.item.camera_name,
                plan.status or "",
                f"{plan.item.confidence:.3f}" if plan.item.confidence is not None else "",
                plan.item.timestamp.isoformat(),
                plan.reviewed_by or "",
                plan.reviewed_at.isoformat() if plan.reviewed_at else "",
                json.dumps(plan.item.bounding_boxes) if plan.item.bounding_boxes else "",
                plan.item.model_id,
                plan.item.model_version,
                plan.item.severity or "",
                plan.item.camera_area or "",
                plan.dismiss_reason or "",
                f"images/{name}",
                f"annotated/{annotated_name}" if annotated_name else "",
                source,
                "true" if is_frame else "false",
                width if width is not None else "",
                height if height is not None else "",
            ]
        )
        counts["images"] += 1
    return counts


def finalize(archive: zipfile.ZipFile, csv_rows: list[list], manifest: dict) -> None:
    """Write the index and manifest, last, so they describe what is there."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    writer.writerows(csv_rows)
    archive.writestr(
        "index.csv", buf.getvalue(), compress_type=zipfile.ZIP_DEFLATED
    )
    archive.writestr(
        "manifest.json",
        json.dumps(manifest, indent=2, default=str),
        compress_type=zipfile.ZIP_DEFLATED,
    )


def open_archive(path: Path) -> zipfile.ZipFile:
    """A ZIP64-capable archive at a temp name, renamed once complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return zipfile.ZipFile(path, "w", zipfile.ZIP_STORED, allowZip64=True)
