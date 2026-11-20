// @vitest-environment jsdom
/**
 * Recommended models and notes in the camera picker (Settings -> AI Models):
 * recommended rows first with a badge, every model's latest visible note
 * under it, and a pointer to the recommended model on the others. Notes an
 * admin marked internal never reach the picker (the server leaves them out).
 */

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import { AIModelSelector } from '../AIModelSelector';
import type { ModelStatusInfo } from '../../../state/api/types';
import { formatNote, pickerModels } from '../pickerState';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function store(model_id: string, over: Partial<ModelStatusInfo> = {}): ModelStatusInfo {
  return {
    model_id, version: '1.0.0', status: 'idle', health: 'healthy', cameras_active: 0,
    last_inference_at: null, started_at: null, source: 'store', ...over,
  } as ModelStatusInfo;
}

const LABELS = { missing_goggles: 'Missing goggles', missing_hardhat: 'Missing hard hat' };

const AVAILABLE = [
  store('no_goggles', { display_name: 'No Goggles', violation_types: ['missing_goggles'], violation_type_labels: LABELS }),
  store('hard_hat', { display_name: 'Hard Hat', violation_types: ['missing_hardhat'], violation_type_labels: LABELS,
    recommended_for: ['missing_hardhat'] }),
  store('goggles_3', { display_name: 'Goggles 3', violation_types: ['missing_goggles'], violation_type_labels: LABELS,
    recommended_for: ['missing_goggles'],
    latest_note: { body: 'Best on the bare-face frame', observed_on: '2026-10-24', project_name: 'HPCL' } }),
  store('fall_pose', { display_name: 'Fall Detection', violation_types: ['fall_detected'] }),
];

describe('recommended models in the picker', () => {
  it('lists recommended models first with their badge; the rest keep their order', () => {
    const rows = pickerModels(AVAILABLE, []);
    expect(rows.map((r) => r.id)).toEqual(['hard_hat', 'goggles_3', 'no_goggles', 'fall_pose']);
    expect(rows[0].recommendedFor).toEqual(['Missing hard hat']);
    expect(rows[1].recommendedFor).toEqual(['Missing goggles']);
    expect(rows[2].recommendedFor).toBeUndefined();
  });

  it('points a non-recommended model at the recommended one, and leaves it selectable', () => {
    const rows = pickerModels(AVAILABLE, []);
    const noGoggles = rows.find((r) => r.id === 'no_goggles')!;
    expect(noGoggles.alternative).toBe('Recommended for Missing goggles: Goggles 3');
    expect(noGoggles.state).toBe('inactive');
    expect(rows.find((r) => r.id === 'fall_pose')!.alternative).toBeUndefined();
    expect(rows.find((r) => r.id === 'goggles_3')!.alternative).toBeUndefined();
  });

  it("shows each model's latest note as one dated line", () => {
    const goggles = pickerModels(AVAILABLE, []).find((r) => r.id === 'goggles_3')!;
    expect(goggles.note).toBe('24 Oct 2026 · HPCL: Best on the bare-face frame');
    expect(formatNote({ body: 'x', observed_on: '2026-11-20', project_name: null })).toBe('20 Nov 2026: x');
  });

  it('changes nothing when no model is recommended', () => {
    const plain = AVAILABLE.map((m) => ({ ...m, recommended_for: [] }));
    expect(pickerModels(plain, []).map((r) => r.id)).toEqual(['no_goggles', 'hard_hat', 'goggles_3', 'fall_pose']);
    expect(pickerModels(plain, []).every((r) => !r.alternative)).toBe(true);
  });

  it('renders the badge, the pointer and the note', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    act(() => root.render(
      <AIModelSelector cameraId="c1" cameraName="CAM" videoUrl="/x" models={pickerModels(AVAILABLE, [])} onModelToggle={vi.fn()} />
    ));
    act(() => (container.querySelector('.ai-model-selector__trigger') as HTMLButtonElement).click());

    const badges = container.querySelectorAll('.ai-model-selector__badge');
    expect(badges).toHaveLength(2);
    expect((badges[0] as HTMLElement).title).toBe('Recommended for Missing hard hat');
    expect(container.querySelector('.ai-model-selector__item-alternative')?.textContent).toBe(
      'Recommended for Missing goggles: Goggles 3'
    );
    expect(container.querySelector('.ai-model-selector__item-note')?.textContent).toContain('HPCL: Best on the bare-face frame');
    const names = [...container.querySelectorAll('.ai-model-selector__model-name')].map((n) => n.textContent);
    expect(names.slice(0, 2)).toEqual(['Hard Hat', 'Goggles 3']);

    act(() => root.unmount());
    container.remove();
  });
});
