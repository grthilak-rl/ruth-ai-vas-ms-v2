"""Card thumbnails: the inferred frame cropped around the detection.

A full 1280x720 frame shrunk to a card is mostly scaffolding; the person and
the box are a few pixels. The thumbnail crops to the boxes with padding —
never below a minimum share of the frame, so there is context — at the
card's 4:3, and draws the box. Only the thumbnail is annotated: the stored
frame stays the clean training image.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path

THUMB_SIZE = (320, 240)
ASPECT = THUMB_SIZE[0] / THUMB_SIZE[1]
#: Padding around the boxes, as a share of the larger box side.
PAD_RATIO = 0.6
#: The crop is never narrower than this share of the frame.
MIN_WIDTH_RATIO = 0.3
BOX_COLOR = (239, 68, 68)


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float


def boxes_in_frame(bounding_boxes, frame_w: int, frame_h: int) -> list[Box]:
    """Stored boxes -> pixel boxes in this frame, skipping unusable ones.

    Boxes are stored in the pixels of the frame they were computed on
    (frame_width/frame_height); rescale if the saved image differs.
    """
    out: list[Box] = []
    for raw in bounding_boxes or []:
        try:
            x, y = float(raw["x"]), float(raw["y"])
            w, h = float(raw["width"]), float(raw["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        sx = frame_w / float(raw.get("frame_width") or frame_w)
        sy = frame_h / float(raw.get("frame_height") or frame_h)
        out.append(Box(x * sx, y * sy, w * sx, h * sy))
    return out


def crop_rect(boxes: list[Box], frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
    """(left, top, right, bottom): 4:3, inside the frame, around the boxes.

    No boxes: the whole frame's centre at 4:3.
    """
    if not boxes:
        w = min(frame_w, frame_h * ASPECT)
        h = w / ASPECT
        left, top = (frame_w - w) / 2, (frame_h - h) / 2
        return round(left), round(top), round(left + w), round(top + h)

    x0 = min(b.x for b in boxes)
    y0 = min(b.y for b in boxes)
    x1 = max(b.x + b.width for b in boxes)
    y1 = max(b.y + b.height for b in boxes)
    pad = PAD_RATIO * max(max(b.width, b.height) for b in boxes)

    w = max(x1 - x0 + 2 * pad, frame_w * MIN_WIDTH_RATIO)
    h = max(y1 - y0 + 2 * pad, w / ASPECT)
    w = max(w, h * ASPECT)
    # Larger than the frame: the biggest 4:3 that fits.
    if w > frame_w or h > frame_h:
        w = min(frame_w, frame_h * ASPECT)
        h = w / ASPECT

    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left = min(max(cx - w / 2, 0), frame_w - w)
    top = min(max(cy - h / 2, 0), frame_h - h)
    return round(left), round(top), round(left + w), round(top + h)


def render_thumbnail(frame_path: Path, bounding_boxes, out_path: Path) -> Path:
    """Crop, scale and annotate; written atomically to ``out_path``."""
    from PIL import Image, ImageDraw

    with Image.open(frame_path) as image:
        image = image.convert("RGB")
        fw, fh = image.size
        boxes = boxes_in_frame(bounding_boxes, fw, fh)
        left, top, right, bottom = crop_rect(boxes, fw, fh)
        thumb = image.crop((left, top, right, bottom)).resize(THUMB_SIZE, Image.LANCZOS)

    scale_x = THUMB_SIZE[0] / (right - left)
    scale_y = THUMB_SIZE[1] / (bottom - top)
    draw = ImageDraw.Draw(thumb)
    for b in boxes:
        draw.rectangle(
            (
                (b.x - left) * scale_x,
                (b.y - top) * scale_y,
                (b.x + b.width - left) * scale_x,
                (b.y + b.height - top) * scale_y,
            ),
            outline=BOX_COLOR,
            width=2,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temp name: two first requests for one card can render at once.
    tmp = out_path.with_name(f"{out_path.name}.{uuid.uuid4().hex}.tmp")
    thumb.save(tmp, "JPEG", quality=80)
    tmp.replace(out_path)
    return out_path
