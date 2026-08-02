/**
 * Shifts API
 *
 * The site-global shift schedule, the shift running right now, and the
 * per-camera count of violations that arrived during it and are still
 * waiting on an operator.
 *
 * The backend owns both the shift arithmetic and the counting. This module
 * never computes a shift boundary: doing so would mean a second
 * implementation of the midnight-crossing rules, running against the
 * browser's clock rather than the server's.
 *
 * Sources:
 * - GET /api/v1/settings/shift-schedule
 * - PUT /api/v1/settings/shift-schedule
 * - GET /api/v1/shifts/current
 * - GET /api/v1/violations/counts/current-shift
 */

import { apiGet, apiPut } from './client';

const SETTINGS_PATH = '/api/v1/settings';
const SHIFTS_PATH = '/api/v1/shifts';
const VIOLATIONS_PATH = '/api/v1/violations';

/** One named shift, as local wall-clock times. */
export interface ShiftDefinition {
  name: string;
  /** "HH:MM" */
  start: string;
  /** "HH:MM" */
  end: string;
}

export type ShiftMode = 'continuous' | 'shifts';

export interface ShiftSchedule {
  mode: ShiftMode;
  /** IANA timezone the wall-clock times are interpreted in. */
  timezone: string;
  shifts: ShiftDefinition[];
}

export interface ShiftScheduleResponse extends ShiftSchedule {
  /**
   * False when the backend is reporting the continuous default because
   * nothing has been saved yet — lets the config UI distinguish "the site
   * chose continuous" from "nobody has set this up".
   */
  is_configured: boolean;
}

/** The shift window containing the server's current instant. */
export interface CurrentShift {
  name: string;
  /** Inclusive ISO 8601 UTC. */
  start: string;
  /** Exclusive ISO 8601 UTC. */
  end: string;
  mode: ShiftMode;
  timezone: string;
  /** Server instant the window was resolved at. */
  server_time: string;
}

export interface ShiftViolationCounts {
  shift: CurrentShift;
  /** camera_id -> unreviewed violations detected during this shift. */
  counts: Record<string, number>;
}

/** Read the site-global shift schedule. */
export async function fetchShiftSchedule(): Promise<ShiftScheduleResponse> {
  return apiGet<ShiftScheduleResponse>(`${SETTINGS_PATH}/shift-schedule`);
}

/**
 * Replace the site-global shift schedule.
 *
 * Rejects with a 422 ApiError when the shifts overlap or fail to cover the
 * full 24 hours; `details.conflicts` names the offending shifts or the
 * uncovered ranges.
 */
export async function updateShiftSchedule(
  schedule: ShiftSchedule & { updated_by?: string }
): Promise<ShiftScheduleResponse> {
  return apiPut<ShiftScheduleResponse>(`${SETTINGS_PATH}/shift-schedule`, schedule);
}

/** Read the shift window containing the server's current instant. */
export async function fetchCurrentShift(): Promise<CurrentShift> {
  return apiGet<CurrentShift>(`${SHIFTS_PATH}/current`);
}

/**
 * Per-camera unreviewed violation counts for the current shift.
 *
 * One request covers a whole grid: pass every camera on screen and the
 * backend returns a count for each, zero-filled. Cameras are sorted so the
 * URL — and therefore the React Query key — is stable regardless of grid
 * ordering.
 */
export async function fetchCurrentShiftViolationCounts(
  cameraIds?: string[]
): Promise<ShiftViolationCounts> {
  const path = `${VIOLATIONS_PATH}/counts/current-shift`;

  if (!cameraIds || cameraIds.length === 0) {
    return apiGet<ShiftViolationCounts>(path);
  }

  const params = new URLSearchParams({ camera_ids: [...cameraIds].sort().join(',') });
  return apiGet<ShiftViolationCounts>(`${path}?${params.toString()}`);
}

/**
 * Milliseconds until a shift ends, floored at zero.
 *
 * Exported so the countdown component and its tests share one definition of
 * "remaining".
 */
export function millisUntilShiftEnd(endIso: string, now: number = Date.now()): number {
  return Math.max(0, new Date(endIso).getTime() - now);
}

/**
 * Human-readable time remaining, at minute resolution ("3h 20m left").
 *
 * Minute resolution is deliberate: it is what the toolbar displays, and it
 * is why the countdown only needs to tick once a minute.
 */
export function formatTimeRemaining(millis: number): string {
  if (millis <= 0) return 'ending now';

  const totalMinutes = Math.floor(millis / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;

  if (hours === 0) return `${minutes}m left`;
  return `${hours}h ${minutes}m left`;
}

/** "19:00–07:00" for the toolbar, from the schedule's wall-clock times. */
export function formatShiftWindow(shift: CurrentShift): string {
  const asLocalHHMM = (iso: string) =>
    new Intl.DateTimeFormat('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: shift.timezone,
    }).format(new Date(iso));

  return `${asLocalHHMM(shift.start)}–${asLocalHHMM(shift.end)}`;
}
