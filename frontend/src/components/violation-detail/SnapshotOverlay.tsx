import { useCallback, useEffect, useRef, useState } from 'react';
import type { DetectionBoundingBox } from '../../state/api';
import './SnapshotOverlay.css';

interface SnapshotOverlayProps {
  /** Proxied snapshot URL (same-origin, so the canvas stays untainted) */
  snapshotUrl: string;
  /** Detection geometry persisted with the violation */
  boundingBoxes?: DetectionBoundingBox[] | null;
  /** Alt text for the underlying image */
  alt: string;
  /** Used to name the exported file */
  violationId: string;
}

/** Box + label colors, matching the live-view PPE overlay (PPE_COLORS). */
const VIOLATION_COLOR = '#ef4444';
const LABEL_TEXT_COLOR = '#ffffff';

/** Stroke and label metrics at 1x. Scaled up for high-resolution exports. */
const BASE_LINE_WIDTH = 3;
const BASE_FONT_PX = 14;
const BASE_LABEL_PAD = 5;

/** Geometry resolved into a single pixel space, ready to draw. */
interface ResolvedBox {
  x: number;
  y: number;
  width: number;
  height: number;
  caption: string;
}

/**
 * Resolve a stored box into {x, y, width, height} regardless of which
 * persistence format it uses, and build its caption.
 *
 * Older inference-loop rows stored corner coordinates under `bbox`; current
 * rows store top-left plus extent. Both are read here so historical
 * violations still render.
 */
function resolveBox(box: DetectionBoundingBox): ResolvedBox | null {
  let x = box.x;
  let y = box.y;
  let width = box.width;
  let height = box.height;

  if (
    (x === undefined || width === undefined) &&
    Array.isArray(box.bbox) &&
    box.bbox.length === 4
  ) {
    const [x1, y1, x2, y2] = box.bbox;
    x = Math.min(x1, x2);
    y = Math.min(y1, y2);
    width = Math.abs(x2 - x1);
    height = Math.abs(y2 - y1);
  }

  if (
    !Number.isFinite(x) ||
    !Number.isFinite(y) ||
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width <= 0 ||
    height <= 0
  ) {
    return null;
  }

  // Label plus raw confidence, e.g. "No Hard Hat 0.62". Reviewers need the
  // exact score to judge borderline detections; the categorical-only rule
  // (F6 §3.1) governs the violation's own confidence field in the metadata
  // sidebar, not per-box detection scores on the evidence image.
  const label = box.label?.trim() || 'Detection';
  const caption =
    typeof box.confidence === 'number' && Number.isFinite(box.confidence)
      ? `${label} ${box.confidence.toFixed(2)}`
      : label;

  return { x, y, width, height, caption };
}

/**
 * Draw boxes onto a context whose coordinate system is already the target
 * pixel space.
 *
 * @param scale Multiplier from source (inference-frame) pixels to target
 *   pixels. Also scales stroke/font so exports at native resolution don't
 *   end up with hairline boxes and unreadable labels.
 */
function drawBoxes(
  ctx: CanvasRenderingContext2D,
  boxes: ResolvedBox[],
  scaleX: number,
  scaleY: number,
  strokeScale: number,
): void {
  const lineWidth = Math.max(1, BASE_LINE_WIDTH * strokeScale);
  const fontPx = Math.max(10, BASE_FONT_PX * strokeScale);
  const pad = BASE_LABEL_PAD * strokeScale;
  const labelHeight = fontPx + pad * 2;

  ctx.font = `bold ${fontPx}px sans-serif`;
  ctx.textBaseline = 'alphabetic';

  boxes.forEach((box) => {
    const x = box.x * scaleX;
    const y = box.y * scaleY;
    const width = box.width * scaleX;
    const height = box.height * scaleY;

    // Box
    ctx.strokeStyle = VIOLATION_COLOR;
    ctx.lineWidth = lineWidth;
    ctx.strokeRect(x, y, width, height);

    // Label chip above the box, flipped inside when there's no room above
    const textWidth = ctx.measureText(box.caption).width;
    const labelY = y - labelHeight >= 0 ? y - labelHeight : y;

    ctx.fillStyle = VIOLATION_COLOR;
    ctx.fillRect(x, labelY, textWidth + pad * 2, labelHeight);

    ctx.fillStyle = LABEL_TEXT_COLOR;
    ctx.fillText(box.caption, x + pad, labelY + labelHeight - pad);
  });
}

/**
 * Snapshot Overlay
 *
 * Renders the violation snapshot with detection boxes composited on top at
 * DISPLAY time, using the same canvas approach and styling as the live-view
 * overlay.
 *
 * HARD RULE: the stored snapshot is training data. It is fetched and rendered
 * unmodified — boxes live on a separate canvas layer and are never written
 * back. The "Download annotated" action composites into a throwaway canvas in
 * the browser, so even the export path cannot touch the stored file.
 *
 * Coordinate mapping: stored boxes are in inference-frame pixels. Source
 * dimensions come from the box metadata (frame_width/frame_height) when
 * present, otherwise from the image's natural size. Everything is scaled to
 * the rendered size, so the overlay stays aligned across responsive layouts
 * and when the snapshot resolution differs from the inference frame.
 */
export function SnapshotOverlay({
  snapshotUrl,
  boundingBoxes,
  alt,
  violationId,
}: SnapshotOverlayProps) {
  const imgRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const [showOverlay, setShowOverlay] = useState(true);
  const [isImageLoaded, setIsImageLoaded] = useState(false);
  const [isExporting, setIsExporting] = useState(false);

  const resolvedBoxes = (boundingBoxes ?? [])
    .map(resolveBox)
    .filter((box): box is ResolvedBox => box !== null);

  const hasBoxes = resolvedBoxes.length > 0;

  /**
   * Source pixel space of the stored coordinates.
   *
   * Prefer the frame dimensions recorded at detection time; fall back to the
   * snapshot's own dimensions for older records that lack them (correct
   * whenever snapshot resolution matches the inference frame).
   */
  const getSourceDimensions = useCallback(
    (img: HTMLImageElement) => {
      const withDims = (boundingBoxes ?? []).find(
        (box) => box.frame_width && box.frame_height,
      );
      return {
        width: withDims?.frame_width || img.naturalWidth,
        height: withDims?.frame_height || img.naturalHeight,
      };
    },
    [boundingBoxes],
  );

  /** Redraw the on-screen overlay at the image's current rendered size. */
  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img || !img.complete || !img.naturalWidth) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const renderedWidth = img.clientWidth;
    const renderedHeight = img.clientHeight;
    if (!renderedWidth || !renderedHeight) return;

    // Back the canvas with device pixels to keep box edges and label text
    // crisp on high-DPI displays, then work in CSS pixels.
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(renderedWidth * dpr);
    canvas.height = Math.round(renderedHeight * dpr);
    canvas.style.width = `${renderedWidth}px`;
    canvas.style.height = `${renderedHeight}px`;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, renderedWidth, renderedHeight);

    if (!showOverlay || !hasBoxes) return;

    const source = getSourceDimensions(img);
    drawBoxes(
      ctx,
      resolvedBoxes,
      renderedWidth / source.width,
      renderedHeight / source.height,
      1,
    );
  }, [getSourceDimensions, hasBoxes, resolvedBoxes, showOverlay]);

  // Redraw on load, toggle, and any layout change that resizes the image.
  useEffect(() => {
    if (!isImageLoaded) return;

    redraw();

    const img = imgRef.current;
    if (!img || typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', redraw);
      return () => window.removeEventListener('resize', redraw);
    }

    const observer = new ResizeObserver(redraw);
    observer.observe(img);
    return () => observer.disconnect();
  }, [isImageLoaded, redraw]);

  const handleImageLoad = useCallback(() => {
    setIsImageLoaded(true);
  }, []);

  /**
   * Composite snapshot + boxes into an off-screen canvas at the snapshot's
   * native resolution and download it. Produces a burned-in image for
   * reports without ever writing to the stored snapshot.
   */
  const handleDownloadAnnotated = useCallback(async () => {
    const img = imgRef.current;
    if (!img || !img.naturalWidth) return;

    setIsExporting(true);
    try {
      const canvas = document.createElement('canvas');
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

      const source = getSourceDimensions(img);
      const scaleX = canvas.width / source.width;
      const scaleY = canvas.height / source.height;

      // Scale stroke/font with the export so a 1080p image doesn't get
      // 3px boxes sized for a ~600px preview.
      const strokeScale = Math.max(1, canvas.width / 640);
      drawBoxes(ctx, resolvedBoxes, scaleX, scaleY, strokeScale);

      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, 'image/jpeg', 0.92),
      );
      if (!blob) return;

      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `violation-${violationId}-annotated.jpg`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } finally {
      setIsExporting(false);
    }
  }, [getSourceDimensions, resolvedBoxes, violationId]);

  return (
    <div className="snapshot-overlay">
      <div className="snapshot-overlay__stage">
        <img
          ref={imgRef}
          src={snapshotUrl}
          alt={alt}
          className="evidence-viewer__image"
          onLoad={handleImageLoad}
        />
        <canvas
          ref={canvasRef}
          className="snapshot-overlay__canvas"
          aria-hidden="true"
        />
      </div>

      {hasBoxes ? (
        <div className="snapshot-overlay__controls">
          <label className="snapshot-overlay__toggle">
            <input
              type="checkbox"
              checked={showOverlay}
              onChange={(e) => setShowOverlay(e.target.checked)}
            />
            <span>
              Show detection overlay
              {resolvedBoxes.length > 1 ? ` (${resolvedBoxes.length})` : ''}
            </span>
          </label>

          <button
            type="button"
            className="snapshot-overlay__download"
            onClick={handleDownloadAnnotated}
            disabled={!isImageLoaded || isExporting}
          >
            {isExporting ? 'Preparing…' : '⬇ Download annotated'}
          </button>
        </div>
      ) : (
        <div className="snapshot-overlay__controls">
          <span className="snapshot-overlay__no-boxes">
            No detection regions recorded for this violation
          </span>
        </div>
      )}
    </div>
  );
}
