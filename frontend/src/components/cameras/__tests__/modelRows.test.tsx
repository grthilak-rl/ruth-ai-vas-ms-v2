// @vitest-environment jsdom
/**
 * The picker's "unavailable" row: Remove sends one removal for that model.
 */

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import { AIModelSelector, type AIModel } from '../AIModelSelector';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('picker rows for models that are not installed', () => {
  it('show the reason and a Remove button that removes the model', () => {
    const models: AIModel[] = [
      { id: 'gloves_2', name: 'Gloves 2', state: 'active', pending: false },
      { id: 'geo_fencing', name: 'Geo Fencing', state: 'unavailable', removable: true, pending: false,
        disabledReason: 'geo_fencing is retired; use geofence' },
      { id: 'fall_pose', name: 'Fall Detection', state: 'degraded', pending: false,
        problem: 'No result for 2 min 0 s: timeout' },
    ];
    const onToggle = vi.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    act(() => root.render(
      <AIModelSelector cameraId="c1" cameraName="CAM" videoUrl="/x" models={models} onModelToggle={onToggle} />
    ));
    act(() => (container.querySelector('.ai-model-selector__trigger') as HTMLButtonElement).click());

    expect(container.textContent).toContain('geo_fencing is retired; use geofence');
    expect(container.textContent).toContain('No result for 2 min 0 s: timeout');
    const removes = container.querySelectorAll('.ai-model-selector__remove-btn');
    expect(removes).toHaveLength(1);
    act(() => (removes[0] as HTMLButtonElement).click());
    expect(onToggle).toHaveBeenCalledExactlyOnceWith('geo_fencing', false);

    act(() => root.unmount());
    container.remove();
  });
});
