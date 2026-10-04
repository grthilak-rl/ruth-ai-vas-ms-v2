/**
 * Overlay rendering: single-model output is identical to before M2, and the
 * multi-model styles change only the label text, label row and line dash.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { drawFallDetections } from '../../../services/fallDetection';
import { drawPPEDetections, transformAPIResponse } from '../../../services/ppeDetection';
import {
  LABEL_ROW_HEIGHT,
  MULTI_MODEL_STYLES,
  overlayStylesFor,
} from '../../../services/overlayStyle';
import { PRE_M2_GOLDEN } from './overlayDraw.golden';
import { runScenarios } from './overlayScenarios';
import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
  FALL_DETECTIONS,
  FIXED_NOW,
  FRAME_HEIGHT,
  FRAME_WIDTH,
  PPE_RAW,
  recordingContext,
  type CanvasCall,
} from './overlaySupport';

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(FIXED_NOW);
});
afterEach(() => {
  vi.useRealTimers();
});

const ppe = () => transformAPIResponse(PPE_RAW, 'full', FRAME_WIDTH, FRAME_HEIGHT);

function drawFall(style?: Parameters<typeof drawFallDetections>[4]): CanvasCall[] {
  const { ctx, calls } = recordingContext();
  drawFallDetections(ctx, FALL_DETECTIONS, CANVAS_WIDTH, CANVAS_HEIGHT, style);
  return calls;
}

function drawPPE(style?: Parameters<typeof drawPPEDetections>[6]): CanvasCall[] {
  const p = ppe();
  const { ctx, calls } = recordingContext();
  drawPPEDetections(ctx, p.detections, CANVAS_WIDTH, CANVAS_HEIGHT, p.videoWidth, p.videoHeight, style);
  return calls;
}

describe('single-model rendering is unchanged', () => {
  it('reproduces the pre-M2 golden call logs exactly', () => {
    const now = runScenarios({ drawFallDetections, drawPPEDetections, transformAPIResponse });
    expect(now).toEqual(PRE_M2_GOLDEN);
  });

  it('covers both fall states and a PPE violation', () => {
    const labels = (calls: CanvasCall[]) =>
      calls.filter(([op]) => op === 'fillText').map(([, text]) => text);
    expect(labels(PRE_M2_GOLDEN.calls.fall)).toEqual(
      expect.arrayContaining(['Person 1', 'Person 2 - FALL'])
    );
    expect(labels(PRE_M2_GOLDEN.calls.ppe)).toContain('Person 1 - PPE VIOLATION');
  });

  it('draws no style with fewer than two models', () => {
    expect(overlayStylesFor(0)).toEqual({});
    expect(overlayStylesFor(1)).toEqual({});
    // What LiveVideoPlayer passes for one model: styles.fall / styles.ppe.
    expect(drawFall(overlayStylesFor(1).fall)).toEqual(PRE_M2_GOLDEN.calls.fall);
    expect(drawPPE(overlayStylesFor(1).ppe)).toEqual(PRE_M2_GOLDEN.calls.ppe);
  });

  it('an empty style is the same as no style', () => {
    expect(drawFall({})).toEqual(PRE_M2_GOLDEN.calls.fall);
    expect(drawPPE({})).toEqual(PRE_M2_GOLDEN.calls.ppe);
  });
});

describe('multi-model styles', () => {
  it('apply from two models on', () => {
    for (const n of [2, 3, 4]) {
      expect(overlayStylesFor(n)).toEqual({
        fall: MULTI_MODEL_STYLES.fall_detection,
        ppe: MULTI_MODEL_STYLES.ppe_detection,
      });
    }
  });

  it('fall: prefixed label, same position, solid box', () => {
    const golden = PRE_M2_GOLDEN.calls.fall;
    const styled = drawFall(overlayStylesFor(2).fall);

    expect(styled.some(([op]) => op === 'setLineDash')).toBe(false);
    // Same calls in the same order; only label text (and its measured width) differs.
    expect(styled.length).toBe(golden.length);
    styled.forEach((call, i) => {
      const before = golden[i];
      if (call[0] === 'fillText' || call[0] === 'measureText') {
        expect(call[1]).toBe(`FALL · ${before[1]}`);
        expect(call.slice(2)).toEqual(before.slice(2));
      } else if (call[0] === 'fillRect' && call[4] === 22 && before[3] !== call[3]) {
        // label background: wider by the prefix, same place
        expect([call[1], call[2], call[4]]).toEqual([before[1], before[2], before[4]]);
        expect(call[3]).toBe((before[3] as number) + 'FALL · '.length * 7);
      } else {
        expect(call).toEqual(before);
      }
    });
  });

  it('PPE: dashed person box, prefixed label one row higher', () => {
    const golden = PRE_M2_GOLDEN.calls.ppe;
    const styled = drawPPE(overlayStylesFor(2).ppe);

    // Every dashed stroke is the person box, and the dash is reset after it.
    const dashOn = styled.flatMap((c, i) => (c[0] === 'setLineDash' && (c[1] as number[]).length ? [i] : []));
    expect(dashOn.length).toBe(ppe().detections.length);
    for (const i of dashOn) {
      expect(styled[i]).toEqual(['setLineDash', [8, 4]]);
      expect(styled[i + 1][0]).toBe('strokeRect');
      expect(styled[i + 2]).toEqual(['setLineDash', []]);
    }

    // Removing the dash calls leaves the same sequence apart from the label.
    const undashed = styled.filter(([op]) => op !== 'setLineDash');
    expect(undashed.length).toBe(golden.length);
    const personLabel = /^Person \d+ - PPE (VIOLATION|OK)$/;
    undashed.forEach((call, i) => {
      const before = golden[i];
      if ((call[0] === 'fillText' || call[0] === 'measureText') && personLabel.test(String(before[1]))) {
        expect(call[1]).toBe(`PPE · ${before[1]}`);
        if (call[0] === 'fillText') {
          expect(call[2]).toBe(before[2]);
          expect(call[3]).toBe((before[3] as number) - LABEL_ROW_HEIGHT);
        }
      } else if (call[0] === 'fillRect' && undashed[i + 2]?.[0] === 'fillText' && personLabel.test(String(golden[i + 2]?.[1]))) {
        // person label background: one row up, wider by the prefix
        expect(call[1]).toBe(before[1]);
        expect(call[2]).toBe((before[2] as number) - LABEL_ROW_HEIGHT);
        expect(call[3]).toBe((before[3] as number) + 'PPE · '.length * 7);
        expect(call[4]).toBe(before[4]);
      } else {
        expect(call).toEqual(before);
      }
    });
  });

  it('fall and PPE person labels do not share a row', () => {
    const labelYs = (calls: CanvasCall[], prefix: string) =>
      calls.filter(([op, text]) => op === 'fillText' && String(text).startsWith(prefix)).map((c) => c[3]);
    const styles = overlayStylesFor(2);
    // Same person box for both models: map the PPE person onto the first fall box.
    const fallY = labelYs(drawFall(styles.fall), 'FALL · ')[0] as number;
    const { ctx, calls } = recordingContext();
    const p = ppe();
    const [x1, y1, x2, y2] = [100, 80, 180, 500].map((v, i) => (v * (i % 2 ? CANVAS_HEIGHT : CANVAS_WIDTH)) / 640);
    const person = { ...p.detections[0], person_bbox: { ...p.detections[0].person_bbox, x1, y1, x2, y2 } };
    drawPPEDetections(ctx, [person], CANVAS_WIDTH, CANVAS_HEIGHT, undefined, undefined, styles.ppe);
    const ppeY = labelYs(calls, 'PPE · ')[0] as number;
    expect(fallY - ppeY).toBe(LABEL_ROW_HEIGHT);
  });
});
