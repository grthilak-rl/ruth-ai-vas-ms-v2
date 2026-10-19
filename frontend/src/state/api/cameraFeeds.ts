/**
 * Camera feed health: is video arriving, and is it being recorded?
 *
 * VAS measures this from evidence — the age of the last decoded frame and of
 * the newest recording segment — and reports it per device as video_state /
 * recording_state. Before that, the only signal was VAS's stream state, which
 * records what VAS *meant* to run: camera 74004 was unreachable for an hour
 * while it read "live", and the tile showed a connection error under a
 * "LIVE" pill.
 *
 * Distinct from coverage.ts (is the AI watching live video?). A camera with
 * no video is a feed problem, not a coverage gap.
 */

import type { Device } from './types';

export type FeedProblem = 'no_video' | 'not_recording';

/** Cameras VAS is expected to be running: video is live, stalled or offline.
 *  Disabled / operator-stopped (idle) cameras, and cameras VAS hasn't
 *  measured yet (null), are not part of the fleet count. */
export function isFeedExpected(device: Device): boolean {
  const s = device.streaming.video_state;
  return s === 'live' || s === 'stalled' || s === 'offline';
}

/**
 * The single most important problem with this camera's feed, or null.
 * No video wins: without frames there is nothing to record either.
 */
export function feedProblem(device: Device): FeedProblem | null {
  const { video_state, recording_state } = device.streaming;
  if (device.enabled === false) return null;
  if (video_state === 'offline' || video_state === 'stalled') return 'no_video';
  if (recording_state === 'stopped') return 'not_recording';
  return null;
}

/** Local clock time, with the date when it isn't today. */
export function formatSince(iso: string | null | undefined, now: number = Date.now()): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return d.toDateString() === new Date(now).toDateString()
    ? time
    : `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${time}`;
}

/** Operator-facing one-liner, e.g. "No video · recording stopped since 10:21". */
export function describeFeedProblem(device: Device, now: number = Date.now()): string {
  const { video_state, last_frame_at, recording_state, last_segment_at } = device.streaming;
  const parts: string[] = [];
  if (video_state === 'offline' || video_state === 'stalled') {
    const since = formatSince(last_frame_at, now);
    parts.push(
      video_state === 'stalled'
        ? `video stalled${since ? ` since ${since}` : ''}`
        : `no video${since ? ` since ${since}` : ''}`
    );
  }
  if (recording_state === 'stopped') {
    const since = formatSince(last_segment_at, now);
    parts.push(since ? `recording stopped since ${since}` : 'not recording');
  }
  const text = parts.join(' · ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export interface FeedSummary {
  /** Expected cameras with live video and an active recording. */
  healthy: number;
  /** Cameras VAS is expected to be running (see isFeedExpected). */
  expected: number;
  /** Expected cameras with a problem, worst (no video) first. */
  problems: { device: Device; problem: FeedProblem }[];
  /** Cameras for which VAS reported no health (older VAS / not measured yet). */
  unknown: number;
}

export function feedSummary(devices: Device[]): FeedSummary {
  const enabled = devices.filter((d) => d.enabled !== false);
  const expected = enabled.filter(isFeedExpected);
  const problems = expected
    .map((device) => ({ device, problem: feedProblem(device) }))
    .filter((p): p is { device: Device; problem: FeedProblem } => p.problem !== null)
    .sort((a, b) => (a.problem === b.problem ? 0 : a.problem === 'no_video' ? -1 : 1));
  return {
    healthy: expected.length - problems.length,
    expected: expected.length,
    problems,
    unknown: enabled.filter((d) => d.streaming.video_state == null).length,
  };
}
