/**
 * Client-side ray-cast radius estimation for the chane_tank_monitor ROI.
 *
 * Mirrors the Python detect_radius_from_center (fill_engine.py): from a clicked
 * center, cast rays outward until brightness jumps past the rim, then take the
 * median hit radius. Runs on the current video frame so the operator gets an
 * instant provisional circle without a server round-trip.
 *
 * Coordinates are in the video's INTRINSIC pixel space (videoWidth/Height),
 * which is exactly what the model's roi_circle expects.
 */

const RAY_DIRECTIONS = 72;
const RAY_MAX_LEN_FRAC = 0.48;
const RAY_EDGE_JUMP = 25;
const RAY_MIN_VALID_FRAC = 0.4;

/** Estimate ROI radius (intrinsic px) from a clicked center on a video frame. */
export function estimateRadiusFromClick(
  video: HTMLVideoElement,
  cx: number,
  cy: number,
): number {
  const fW = video.videoWidth;
  const fH = video.videoHeight;
  const fallback = Math.round(Math.min(fH, fW) * 0.15);
  if (fW === 0 || fH === 0) return fallback;

  // Grab the current frame into an offscreen canvas (grayscale read).
  const canvas = document.createElement('canvas');
  canvas.width = fW;
  canvas.height = fH;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return fallback;
  ctx.drawImage(video, 0, 0, fW, fH);

  let img: ImageData;
  try {
    img = ctx.getImageData(0, 0, fW, fH);
  } catch {
    // Tainted canvas (cross-origin) — fall back to a sane default radius.
    return fallback;
  }
  const data = img.data;
  const gray = (x: number, y: number): number => {
    const i = (y * fW + x) * 4;
    // Rec.601 luma.
    return 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
  };

  const maxLen = Math.round(Math.min(fH, fW) * RAY_MAX_LEN_FRAC);
  const interiorR = Math.max(5, Math.floor(maxLen / 10));

  // Mean brightness of the interior patch around the click.
  let sum = 0;
  let count = 0;
  for (let y = Math.max(0, cy - interiorR); y < Math.min(fH, cy + interiorR); y++) {
    for (let x = Math.max(0, cx - interiorR); x < Math.min(fW, cx + interiorR); x++) {
      sum += gray(x, y);
      count++;
    }
  }
  if (count === 0) return fallback;
  const interiorMean = sum / count;

  const radii: number[] = [];
  for (let k = 0; k < RAY_DIRECTIONS; k++) {
    const angle = (2 * Math.PI * k) / RAY_DIRECTIONS;
    const dx = Math.cos(angle);
    const dy = Math.sin(angle);
    for (let d = interiorR + 2; d < maxLen; d++) {
      const px = Math.round(cx + dx * d);
      const py = Math.round(cy + dy * d);
      if (px < 0 || px >= fW || py < 0 || py >= fH) break;
      if (gray(px, py) - interiorMean > RAY_EDGE_JUMP) {
        radii.push(d);
        break;
      }
    }
  }

  const minValid = Math.floor(RAY_DIRECTIONS * RAY_MIN_VALID_FRAC);
  if (radii.length >= minValid) {
    radii.sort((a, b) => a - b);
    const mid = Math.floor(radii.length / 2);
    return radii.length % 2
      ? radii[mid]
      : Math.round((radii[mid - 1] + radii[mid]) / 2);
  }
  return fallback;
}
