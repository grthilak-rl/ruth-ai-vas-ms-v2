/**
 * File name for a downloaded evidence clip:
 * `<camera>_<type>_<timestamp>.mp4`, e.g.
 * `Dock-2_missing_gloves_20261019T091952Z.mp4`.
 *
 * Every part is reduced to filename-safe characters, so a camera called
 * "Gate 3 / North" can't produce a path or a name some OS rejects.
 */
function safe(part: string): string {
  return (
    part
      .trim()
      .replace(/[^A-Za-z0-9_-]+/g, '-')
      .replace(/-{2,}/g, '-')
      .replace(/^-|-$/g, '') || 'unknown'
  );
}

/** ISO timestamp -> `20261019T091952Z` (UTC, no separators). */
function compactTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return safe(iso);
  return date.toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
}

export function clipFilename(cameraName: string, typeSlug: string, timestamp: string): string {
  return `${safe(cameraName)}_${safe(typeSlug)}_${compactTimestamp(timestamp)}.mp4`;
}
