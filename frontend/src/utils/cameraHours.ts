/**
 * Rates per monitored camera-hour: a count divided by the hours cameras
 * actually ran AI detection (stream sessions). Time a camera was off,
 * disabled or had no models does not count, so it does not dilute the rate.
 *
 * Analytics counts raw *violations* (detections); customer reports count
 * *incidents* (detections grouped per camera and type). The two rates differ
 * by design (HPCL: 7.4 vs 0.96 over the same 4,640 h), so every label says
 * which one it is.
 */

export const VIOLATIONS_PER_CAMERA_HOUR = 'violations per monitored camera-hour';

/** "0.42", "2.3", "17"; an em dash when nothing was monitored. */
export function formatCameraHourRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return '—';
  if (rate >= 10) return Math.round(rate).toLocaleString();
  return rate >= 1 ? rate.toFixed(1) : rate.toFixed(2);
}

/** Monitored hours, rounded for display: "0.5 h", "36 h", "4,120 h". */
export function formatMonitoredHours(hours: number | null | undefined): string {
  if (!hours) return '0 h';
  return hours < 10 ? `${hours.toFixed(1)} h` : `${Math.round(hours).toLocaleString()} h`;
}
