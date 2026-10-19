import { describe, it, expect } from 'vitest';
import type { Device, DeviceStreaming } from '../types';
import { describeFeedProblem, feedProblem, feedSummary } from '../cameraFeeds';
import { coverageSummary } from '../coverage';

const NOW = Date.parse('2026-10-19T11:23:00Z');

function camera(name: string, streaming: Partial<DeviceStreaming>, extra: Partial<Device> = {}): Device {
  return {
    id: name,
    name,
    is_active: true,
    enabled: true,
    streaming: {
      video_live: false,
      active: false,
      stream_id: null,
      state: null,
      ai_enabled: false,
      model_id: null,
      model_config: null,
      ...streaming,
    },
    ...extra,
  } as Device;
}

// 74004 as VAS reports it after the fix: stream row still "live", but no
// frames for an hour and no segment since 10:21:56.
const DEAD = camera('74004', {
  video_live: false,
  video_state: 'offline',
  recording_state: 'stopped',
  last_segment_at: '2026-10-19T10:21:56Z',
  segments_today: 6213,
});
const HEALTHY = camera('75080', {
  video_live: true,
  active: true,
  video_state: 'live',
  recording_state: 'recording',
  last_segment_at: '2026-10-19T11:22:56Z',
});
const NOT_RECORDING = camera('75081', { video_live: true, video_state: 'live', recording_state: 'stopped' });

describe('feedProblem', () => {
  it('reports no video ahead of not recording', () => {
    expect(feedProblem(DEAD)).toBe('no_video');
    expect(feedProblem(NOT_RECORDING)).toBe('not_recording');
    expect(feedProblem(HEALTHY)).toBeNull();
  });

  it('ignores disabled cameras and cameras without health', () => {
    expect(feedProblem({ ...DEAD, enabled: false })).toBeNull();
    expect(feedProblem(camera('old', { video_live: true }))).toBeNull();
  });

  it('describes when recording stopped', () => {
    expect(describeFeedProblem(DEAD, NOW)).toMatch(/^No video · recording stopped since /);
  });
});

describe('feedSummary', () => {
  it('counts healthy of expected and lists the dead camera first', () => {
    const idle = camera('75099', { video_state: 'idle', recording_state: 'idle' });
    const s = feedSummary([HEALTHY, NOT_RECORDING, DEAD, idle]);
    expect(s.healthy).toBe(1);
    expect(s.expected).toBe(3); // idle (operator-stopped) not expected
    expect(s.problems.map((p) => p.device.name)).toEqual(['74004', '75081']);
  });
});

describe('coverage with feed health', () => {
  it('treats a camera with no video as no_video, named, not as uncovered', () => {
    const s = coverageSummary([HEALTHY, DEAD], NOW);
    expect(s.uncovered).toHaveLength(0);
    expect(s.expected).toBe(1);
    expect(s.noVideoDevices.map((d) => d.name)).toEqual(['74004']);
  });
});
