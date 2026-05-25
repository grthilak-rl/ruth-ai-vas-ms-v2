/**
 * Time-formatting helpers used across the bookmark-analysis UI.
 *
 * Pure functions, no React. The split between ``formatTimestamp``
 * (mm:ss video-style stamps for chart axes and crossing markers) and
 * ``formatDuration`` (human-readable spans like "25m 12s" for stat
 * cards) is intentional — they have different display goals.
 */

/** Round-half-to-even isn't worth the complexity here; plain rounding. */
function roundSeconds(seconds: number): number {
  return Math.max(0, Math.round(seconds));
}

/**
 * Format a number of seconds as a video-style timestamp.
 *
 * - Under one hour: ``mm:ss`` (e.g. ``00:25`` or ``12:34``)
 * - One hour or more: ``hh:mm:ss``
 *
 * Always zero-padded so widths stay aligned in tables and axes.
 */
export function formatTimestamp(seconds: number): string {
  const total = roundSeconds(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const ss = String(secs).padStart(2, '0');
  const mm = String(minutes).padStart(2, '0');
  if (hours === 0) {
    return `${mm}:${ss}`;
  }
  return `${hours}:${mm}:${ss}`;
}

/**
 * Format a duration as a human-readable span.
 *
 * - Under one minute: ``<seconds>s`` (no zero-pad)
 * - Under one hour: ``<m>m <s>s`` (seconds dropped when 0)
 * - One hour or more: ``<h>h <m>m`` (seconds dropped)
 *
 * Examples: ``45s``, ``2m 30s``, ``25m 12s``, ``1h 5m``.
 */
export function formatDuration(seconds: number): string {
  const total = roundSeconds(seconds);
  if (total < 60) {
    return `${total}s`;
  }
  if (total < 3600) {
    const m = Math.floor(total / 60);
    const s = total % 60;
    return s === 0 ? `${m}m` : `${m}m ${s}s`;
  }
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}
