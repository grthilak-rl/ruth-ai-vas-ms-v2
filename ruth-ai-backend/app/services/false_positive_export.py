"""Copy false-alarm dismissals to the labelling set for the AI engineer.

When an operator dismisses a violation as a false alarm, the inferred frame
(the exact image the model was given) is a training example the model got
wrong. It is copied to

    <labelling root>/false_positives/<model_id>/<YYYY-MM-DD>/<violation_id>.jpg

with a ``.json`` sidecar holding the boxes in frame pixels, the frame size,
the model and version, the type, confidence, reason and camera. For reasons
where the frame contains none of the model's target (pipework/object, PPE
actually worn) an empty YOLO ``.txt`` is written too, so the image can be
dropped into a dataset as a background (negative) example as-is.

Only the inferred frame is used: the scene snapshot is a later capture whose
boxes do not line up, so it would teach the wrong thing. Violations without
a saved frame are skipped and counted.

Exporting must never fail a dismissal: errors are logged and counted, and
every file is written atomically (temp name, then rename), so a half-written
pair is never left for a training run to pick up.
"""

import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.logging import get_logger
from app.models.dismiss_reasons import (
    FALSE_ALARM_REASONS,
    REASON_LABELS,
    YOLO_BACKGROUND_REASONS,
    DismissReason,
)

logger = get_logger(__name__)

#: At most this many frames per incident-like group (same camera + type) in
#: one action: a long incident is mostly near-identical frames.
MAX_PER_GROUP = 50


@dataclass
class ExportItem:
    """Everything one export needs, gathered while the session was open."""

    violation_id: uuid.UUID
    model_id: str
    model_version: str
    type: str
    type_detail: str | None
    severity: str | None
    confidence: float
    timestamp: datetime
    camera_name: str
    camera_display_name: str | None
    camera_area: str | None
    camera_in_out: str | None
    bounding_boxes: list | None
    #: Relative to the evidence frame dir; None when no frame was saved.
    frame_file: str | None
    group_key: str = ""
    #: Review state at export time. Carried for the operator-facing bulk
    #: export, which includes reviewed and dismissed violations; the
    #: dismissal path leaves it None because the status is implied.
    status: str | None = None


@dataclass
class ExportResult:
    exported: int = 0
    no_frame: int = 0
    failed: int = 0
    capped: int = 0
    paths: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "exported": self.exported,
            "no_frame": self.no_frame,
            "failed": self.failed,
            "capped": self.capped,
        }


def is_false_alarm(reason: DismissReason | str | None) -> bool:
    try:
        return reason is not None and DismissReason(reason) in FALSE_ALARM_REASONS
    except ValueError:
        return False


def _safe_segment(value: str) -> str:
    """A path segment that cannot escape the labelling root."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "").strip("._")
    return cleaned or "unknown"


def _write_atomic(path: Path, write) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        write(tmp)
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _frame_size(path: Path, boxes: list | None) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except Exception:  # noqa: BLE001 - size is best effort; boxes may carry it
        for box in boxes or []:
            if isinstance(box, dict) and box.get("frame_width") and box.get("frame_height"):
                return int(box["frame_width"]), int(box["frame_height"])
        return None, None


#: What the image in a sidecar's ``image`` field actually is.
EVIDENCE_INFERRED_FRAME = "inferred_frame"
EVIDENCE_SCENE_SNAPSHOT = "scene_snapshot"


def build_sidecar(
    item: ExportItem,
    *,
    image_name: str,
    width: int | None,
    height: int | None,
    evidence_source: str = EVIDENCE_INFERRED_FRAME,
    boxes_apply_to_image: bool = True,
    extra: dict | None = None,
) -> dict:
    """The per-image JSON that travels with every exported image.

    One builder for both exports — the dismissal-driven labelling copy and
    the operator's bulk download — so the AI engineer never has to deal with
    two shapes of the same record.

    ``boxes_apply_to_image`` is not decoration. Boxes are in the pixel space
    of the frame the model was given; the scene snapshot is a later capture
    of a moved scene, so its boxes do not line up. A consumer must be able
    to tell, from the file alone, whether drawing them would be a lie.
    """
    sidecar = {
        "violation_id": str(item.violation_id),
        "image": image_name,
        "evidence_source": evidence_source,
        "boxes_apply_to_image": boxes_apply_to_image,
        "frame": {"width": width, "height": height},
        "boxes": [
            {
                "x": b.get("x"),
                "y": b.get("y"),
                "width": b.get("width"),
                "height": b.get("height"),
                "label": b.get("label"),
                "confidence": b.get("confidence"),
                "frame_width": b.get("frame_width"),
                "frame_height": b.get("frame_height"),
            }
            for b in (item.bounding_boxes or [])
            if isinstance(b, dict)
        ],
        "box_units": "pixels of the frame given in each box (frame_width x frame_height)",
        "model_id": item.model_id,
        "model_version": item.model_version,
        "type": item.type,
        "type_detail": item.type_detail,
        "severity": item.severity,
        "status": item.status,
        "confidence": item.confidence,
        "detected_at": item.timestamp.isoformat(),
        "camera": {
            "name": item.camera_name,
            "display_name": item.camera_display_name,
            "area": item.camera_area,
            "in_out": item.camera_in_out,
        },
    }
    if extra:
        sidecar.update(extra)
    return sidecar


def export_false_positives(
    items: list[ExportItem],
    reason: DismissReason | str,
    note: str | None,
    *,
    frame_root: Path,
    labelling_root: Path,
    dismissed_by: str | None = None,
    now: datetime | None = None,
) -> ExportResult:
    """Write the labelling files for each item. Blocking; run in a thread."""
    result = ExportResult()
    reason = DismissReason(reason)
    if reason not in FALSE_ALARM_REASONS:
        return result

    background = reason in YOLO_BACKGROUND_REASONS
    dismissed_at = (now or datetime.now(timezone.utc)).isoformat()
    frame_root = frame_root.resolve()
    per_group: dict[str, int] = {}

    for item in items:
        if not item.frame_file:
            result.no_frame += 1
            continue
        frame = (frame_root / item.frame_file).resolve()
        if not frame.is_relative_to(frame_root) or not frame.is_file():
            result.no_frame += 1
            continue
        if per_group.get(item.group_key, 0) >= MAX_PER_GROUP:
            result.capped += 1
            continue

        day = item.timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d")
        out_dir = labelling_root / "false_positives" / _safe_segment(item.model_id) / day
        stem = str(item.violation_id)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            width, height = _frame_size(frame, item.bounding_boxes)
            sidecar = build_sidecar(
                item,
                image_name=f"{stem}.jpg",
                width=width,
                height=height,
                # Always the inferred frame here: items without one were
                # skipped above, precisely because snapshot boxes would
                # teach the wrong thing.
                evidence_source=EVIDENCE_INFERRED_FRAME,
                boxes_apply_to_image=True,
                extra={
                    "dismiss_reason": reason.value,
                    "dismiss_reason_label": REASON_LABELS[reason],
                    "note": note,
                    "dismissed_by": dismissed_by,
                    "dismissed_at": dismissed_at,
                    "yolo_background": background,
                },
            )
            _write_atomic(out_dir / f"{stem}.jpg", lambda p: shutil.copyfile(frame, p))
            _write_atomic(
                out_dir / f"{stem}.json",
                lambda p: p.write_text(json.dumps(sidecar, indent=2, default=str)),
            )
            label = out_dir / f"{stem}.txt"
            if background:
                _write_atomic(label, lambda p: p.write_text(""))
            elif label.exists():
                # Re-dismissed with a reason that is not background: the old
                # empty label would now assert something untrue.
                label.unlink()
        except OSError as e:
            result.failed += 1
            logger.warning(
                "False-positive export failed",
                violation_id=stem,
                model_id=item.model_id,
                error=str(e),
            )
            continue

        per_group[item.group_key] = per_group.get(item.group_key, 0) + 1
        result.exported += 1
        result.paths.append(str(out_dir / f"{stem}.jpg"))

    if result.exported or result.failed:
        logger.info(
            "Exported false positives for labelling",
            reason=reason.value,
            **result.as_dict(),
        )
    return result
