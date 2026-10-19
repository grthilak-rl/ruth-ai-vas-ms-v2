/**
 * Monitoring coverage: which cameras have live video but no AI inference.
 *
 * BL-11. Camera 74004 ran for 21.3 hours with its video stream live and no
 * inference at all, and nothing anywhere said so — the device was enabled,
 * active and streaming, so every indicator read healthy. A plant believing
 * a camera is monitored when it is not is the failure this product most
 * needs not to have.
 *
 * The signal is a conjunction that was never expressed in one place:
 *
 *     video_live === true   AND   active === false
 *
 * Both halves already come back from GET /api/v1/devices. What was missing
 * is the *duration*, because inference legitimately drops out for a few
 * seconds during a backend restart or a model change, and alerting on the
 * instantaneous state would fire on every deploy. The backend supplies
 * `inference_absent_since` so the duration survives a page reload — timing
 * it in the browser would restart the clock on every refresh, which is
 * precisely how a 21-hour gap stays invisible.
 */

import type { Device } from './types';

/**
 * How long a camera may be uncovered before it counts.
 *
 * Three minutes: long enough to ride out a backend restart and a model
 * change (both seconds to tens of seconds), short enough that a real gap
 * is visible within one shift handover rather than one day. Deliberately
 * not seconds — that would page somebody on every deploy — and not an
 * hour, which is how this went unnoticed.
 */
export const COVERAGE_GRACE_MS = 3 * 60 * 1000;

export type CoverageState =
  /** Video live and inference running. The normal case. */
  | 'covered'
  /** Video live, inference absent, but inside the grace window. */
  | 'settling'
  /** Video live, inference absent beyond the grace window. The alert. */
  | 'uncovered'
  /** No live video, so inference is not expected. Not a coverage problem. */
  | 'no_video';

export interface CameraCoverage {
  device: Device;
  state: CoverageState;
  /** Milliseconds since inference stopped; null when unknown or covered. */
  absentForMs: number | null;
}

/**
 * Classify one camera.
 *
 * `now` is injectable so this is testable without faking the clock.
 */
export function cameraCoverage(device: Device, now: number = Date.now()): CameraCoverage {
  const { video_live, active, inference_absent_since } = device.streaming;

  // No video means inference is not expected to be running, so its absence
  // is not a coverage gap. A camera that is genuinely offline is a
  // different problem, shown as "Offline" / NO VIDEO. video_live is derived
  // server-side from VAS's measured video_state, so a camera that vanished
  // while its stream still read "live" lands here, not in "uncovered".
  if (!video_live) {
    return { device, state: 'no_video', absentForMs: null };
  }

  if (active) {
    return { device, state: 'covered', absentForMs: null };
  }

  // Uncovered. How long for?
  //
  // A null timestamp here means inference has NEVER run on this camera.
  // That is uncovered too, and for longer than any timestamp could say —
  // so it skips the grace window rather than being treated as fresh.
  if (!inference_absent_since) {
    return { device, state: 'uncovered', absentForMs: null };
  }

  const since = Date.parse(inference_absent_since);
  if (Number.isNaN(since)) {
    // An unparseable timestamp must not quietly become "covered".
    return { device, state: 'uncovered', absentForMs: null };
  }

  // Clock skew between server and browser can make this negative. Clamp,
  // rather than letting a skewed clock report a camera as covered.
  const absentForMs = Math.max(0, now - since);
  return {
    device,
    state: absentForMs >= COVERAGE_GRACE_MS ? 'uncovered' : 'settling',
    absentForMs,
  };
}

export interface CoverageSummary {
  /** Cameras with live video and running inference. */
  covered: number;
  /** Cameras where inference is expected: covered + settling + uncovered. */
  expected: number;
  /** Past the grace window — the ones worth acting on. */
  uncovered: CameraCoverage[];
  /** Absent, but still inside the grace window. */
  settling: CameraCoverage[];
  /** No live video; excluded from the ratio entirely. */
  noVideo: number;
  /** The cameras behind `noVideo`, so they can be named rather than counted. */
  noVideoDevices: Device[];
}

/**
 * Fleet summary for the System Health tab.
 *
 * The ratio counts only cameras where inference is *expected* — those with
 * live video. Including offline cameras would make the number drift with
 * unrelated video problems and turn a safety signal into noise.
 */
export function coverageSummary(
  devices: Device[],
  now: number = Date.now()
): CoverageSummary {
  const all = devices.map((d) => cameraCoverage(d, now));
  const uncovered = all.filter((c) => c.state === 'uncovered');
  const settling = all.filter((c) => c.state === 'settling');
  const covered = all.filter((c) => c.state === 'covered').length;
  const noVideoDevices = all.filter((c) => c.state === 'no_video').map((c) => c.device);

  return {
    covered,
    expected: covered + settling.length + uncovered.length,
    uncovered,
    settling,
    noVideo: noVideoDevices.length,
    noVideoDevices,
  };
}

/** "21.3 hours", "4 minutes" — for the operator-facing message. */
export function formatAbsentFor(ms: number | null): string {
  if (ms === null) return 'never started';
  const minutes = ms / 60000;
  if (minutes < 60) return `${Math.max(1, Math.round(minutes))} min`;
  const hours = minutes / 60;
  if (hours < 24) return `${hours.toFixed(1)} hours`;
  return `${(hours / 24).toFixed(1)} days`;
}
