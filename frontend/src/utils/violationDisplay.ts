/**
 * How the Violations page names cameras, severities and incident spans.
 */

import type { Severity } from '../state/api';

type CameraSource = {
  camera_name: string;
  camera_display_name?: string | null;
  camera_area?: string | null;
  camera_in_out?: string | null;
};

/**
 * Card headline for a camera: "REFORMER1 · OUT" from its structured naming,
 * else its display name, else its number. The number is shown separately
 * (cameraNumber), so the headline never repeats it.
 */
export function cameraHeadline(camera: CameraSource): string {
  const area = camera.camera_area?.trim();
  const side = camera.camera_in_out?.trim();
  if (area) return side ? `${area} · ${side}` : area;
  return camera.camera_display_name?.trim() || camera.camera_name;
}

/** The camera's number/identifier ("75081"), shown as a chip. */
export function cameraNumber(camera: CameraSource): string {
  return camera.camera_name;
}

/** Most to least severe. */
export const SEVERITY_LEVELS: Severity[] = ['critical', 'high', 'medium', 'low'];

const SEVERITY_LABELS: Record<Severity, string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
};

export function isSeverity(value: unknown): value is Severity {
  return typeof value === 'string' && (SEVERITY_LEVELS as string[]).includes(value);
}

/** Display label; unknown values read as Medium, the backend's default. */
export function severityLabel(value: unknown): string {
  return isSeverity(value) ? SEVERITY_LABELS[value] : SEVERITY_LABELS.medium;
}

/** A severity the UI can style, defaulting to medium. */
export function severityOrDefault(value: unknown): Severity {
  return isSeverity(value) ? value : 'medium';
}

function clock(date: Date): string {
  return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

/**
 * "10:02 AM" for one moment, "10:02 – 10:31 AM"-style for a span on one day,
 * with the date added when the span crosses midnight.
 */
export function formatIncidentSpan(firstAt: string, lastAt: string): string {
  const first = new Date(firstAt);
  const last = new Date(lastAt);
  if (Number.isNaN(first.getTime()) || Number.isNaN(last.getTime())) return '';
  if (last.getTime() - first.getTime() < 60_000) return clock(last);
  if (first.toDateString() === last.toDateString()) return `${clock(first)} – ${clock(last)}`;
  const day = (d: Date) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  return `${day(first)} ${clock(first)} – ${day(last)} ${clock(last)}`;
}
