import { describe, expect, it } from 'vitest';
import {
  COVERAGE_GRACE_MS,
  cameraCoverage,
  coverageSummary,
  formatAbsentFor,
} from '../coverage';
import type { Device } from '../types';

/**
 * BL-11. The real incident these tests encode: camera 74004 ran 21.3 hours
 * with live video and no inference, and every indicator read healthy.
 *
 * The cases that matter are the ones where a wrong answer is *silent* —
 * a camera classified "covered" when it is not. Each of those gets its
 * own test, because the cost of getting one wrong is a plant believing it
 * is monitored when it is not.
 */

const NOW = Date.parse('2026-10-17T12:00:00Z');

function device(
  streaming: Partial<Device['streaming']>,
  name = 'CAM'
): Device {
  return {
    id: `id-${name}`,
    name,
    is_active: true,
    enabled: true,
    streaming: {
      video_live: true,
      stream_id: 's1',
      active: true,
      state: 'live',
      ai_enabled: true,
      model_id: 'safety_vest',
      models: ['safety_vest'],
      ai_model_config: null,
      inference_absent_since: null,
      ...streaming,
    },
  } as Device;
}

function agoMs(ms: number): string {
  return new Date(NOW - ms).toISOString();
}

// ---------------------------------------------------------------------------
// The normal cases
// ---------------------------------------------------------------------------

describe('cameraCoverage', () => {
  it('video live + inference running -> covered', () => {
    expect(cameraCoverage(device({}), NOW).state).toBe('covered');
  });

  it('no video -> not a coverage problem', () => {
    // A camera that is genuinely offline shows as "Offline" already; its
    // lack of inference is expected, not a gap.
    const c = cameraCoverage(device({ video_live: false, active: false }), NOW);
    expect(c.state).toBe('no_video');
  });

  it('no video even with inference somehow running -> no_video', () => {
    expect(
      cameraCoverage(device({ video_live: false, active: true }), NOW).state
    ).toBe('no_video');
  });
});

// ---------------------------------------------------------------------------
// The debounce
// ---------------------------------------------------------------------------

describe('grace window', () => {
  it('a brief absence is settling, not an alert', () => {
    // A backend restart or model change drops inference for seconds.
    // Alerting on that would page somebody on every deploy.
    const c = cameraCoverage(
      device({ active: false, inference_absent_since: agoMs(30_000) }),
      NOW
    );
    expect(c.state).toBe('settling');
    expect(c.absentForMs).toBe(30_000);
  });

  it('past the grace window it is uncovered', () => {
    const c = cameraCoverage(
      device({ active: false, inference_absent_since: agoMs(COVERAGE_GRACE_MS + 1000) }),
      NOW
    );
    expect(c.state).toBe('uncovered');
  });

  it('exactly at the boundary counts as uncovered', () => {
    const c = cameraCoverage(
      device({ active: false, inference_absent_since: agoMs(COVERAGE_GRACE_MS) }),
      NOW
    );
    expect(c.state).toBe('uncovered');
  });

  it('reproduces the 74004 incident', () => {
    const c = cameraCoverage(
      device({ active: false, inference_absent_since: agoMs(21.3 * 3600_000) }, '74004'),
      NOW
    );
    expect(c.state).toBe('uncovered');
    expect(formatAbsentFor(c.absentForMs)).toBe('21.3 hours');
  });
});

// ---------------------------------------------------------------------------
// The silent-failure cases
// ---------------------------------------------------------------------------

describe('never reports "covered" on bad data', () => {
  it('never-started camera is uncovered, not settling', () => {
    // null means inference has NEVER run. That is uncovered for longer
    // than any timestamp could express, so it must skip the grace window
    // rather than be treated as a fresh absence.
    const c = cameraCoverage(
      device({ active: false, inference_absent_since: null }),
      NOW
    );
    expect(c.state).toBe('uncovered');
    expect(c.absentForMs).toBeNull();
    expect(formatAbsentFor(c.absentForMs)).toBe('never started');
  });

  it('an unparseable timestamp is uncovered, not covered', () => {
    const c = cameraCoverage(
      device({ active: false, inference_absent_since: 'not-a-date' }),
      NOW
    );
    expect(c.state).toBe('uncovered');
  });

  it('clock skew cannot make a camera look covered', () => {
    // Server clock ahead of the browser: a future timestamp would give a
    // negative duration, which must not read as "settling forever".
    const c = cameraCoverage(
      device({ active: false, inference_absent_since: agoMs(-60_000) }),
      NOW
    );
    expect(c.absentForMs).toBe(0);
    expect(c.state).toBe('settling'); // clamped, and visible as absent
    expect(c.state).not.toBe('covered');
  });
});

// ---------------------------------------------------------------------------
// Fleet summary
// ---------------------------------------------------------------------------

describe('coverageSummary', () => {
  it('counts only cameras where inference is expected', () => {
    // Offline cameras are excluded from the ratio: including them would
    // make a safety signal drift with unrelated video problems.
    const s = coverageSummary(
      [
        device({}, 'A'),
        device({}, 'B'),
        device({ active: false, inference_absent_since: agoMs(3600_000) }, 'C'),
        device({ video_live: false, active: false }, 'D'),
      ],
      NOW
    );
    expect(s.covered).toBe(2);
    expect(s.expected).toBe(3); // D excluded
    expect(s.noVideo).toBe(1);
    expect(s.uncovered.map((c) => c.device.name)).toEqual(['C']);
  });

  it('settling cameras count as expected but not covered', () => {
    const s = coverageSummary(
      [device({}, 'A'), device({ active: false, inference_absent_since: agoMs(10_000) }, 'B')],
      NOW
    );
    expect(s.covered).toBe(1);
    expect(s.expected).toBe(2);
    expect(s.settling).toHaveLength(1);
    expect(s.uncovered).toHaveLength(0);
  });

  it('the real fleet: 11 of 12 covered', () => {
    const fleet = [
      ...Array.from({ length: 11 }, (_, i) => device({}, `cam${i}`)),
      device({ active: false, inference_absent_since: agoMs(21.3 * 3600_000) }, '74004'),
    ];
    const s = coverageSummary(fleet, NOW);
    expect(`${s.covered} of ${s.expected}`).toBe('11 of 12');
    expect(s.uncovered[0].device.name).toBe('74004');
  });

  it('an empty fleet does not divide by zero', () => {
    const s = coverageSummary([], NOW);
    expect(s).toMatchObject({ covered: 0, expected: 0, noVideo: 0 });
    expect(s.uncovered).toEqual([]);
  });
});

describe('formatAbsentFor', () => {
  it.each([
    [null, 'never started'],
    [30_000, '1 min'],
    [5 * 60_000, '5 min'],
    [90 * 60_000, '1.5 hours'],
    [21.3 * 3600_000, '21.3 hours'],
    [50 * 3600_000, '2.1 days'],
  ])('%s -> %s', (ms, expected) => {
    expect(formatAbsentFor(ms as number | null)).toBe(expected);
  });
});
