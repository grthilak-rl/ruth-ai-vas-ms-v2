// @vitest-environment jsdom
/**
 * Recommended models in the camera picker (Settings -> AI Models): the
 * recommended rows come first with a badge, and that is all. Notes, and
 * pointers to the recommended model, stay on the model's page so the
 * picker list stays compact.
 */

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import { AIModelSelector } from '../AIModelSelector';
import type { ModelStatusInfo } from '../../../state/api/types';
import { pickerModels } from '../pickerState';

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

  it('adds no note or pointer to any row; non-recommended models stay selectable', () => {
    const rows = pickerModels(AVAILABLE, []);
    for (const row of rows) {
      expect(Object.keys(row)).not.toContain('note');
      expect(Object.keys(row)).not.toContain('alternative');
    }
    expect(rows.find((r) => r.id === 'no_goggles')!.state).toBe('inactive');
  });

  it('changes nothing when no model is recommended', () => {
    const plain = AVAILABLE.map((m) => ({ ...m, recommended_for: [] }));
    expect(pickerModels(plain, []).map((r) => r.id)).toEqual(['no_goggles', 'hard_hat', 'goggles_3', 'fall_pose']);
  });

  it('renders only the badge: no note, no pointer, rows stay one line', () => {
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
    expect(container.textContent).not.toContain('Best on the bare-face frame');
    expect(container.textContent).not.toContain('Recommended for Missing goggles: Goggles 3');
    expect(container.querySelectorAll('.ai-model-selector__item--with-reason')).toHaveLength(0);
    const names = [...container.querySelectorAll('.ai-model-selector__model-name')].map((n) => n.textContent);
    expect(names.slice(0, 2)).toEqual(['Hard Hat', 'Goggles 3']);

    act(() => root.unmount());
    container.remove();
  });
});
