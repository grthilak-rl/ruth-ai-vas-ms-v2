// @vitest-environment jsdom
/**
 * "Camera models" in System Health and the top-nav alert: a model failing
 * on every frame (or not installed) is named, by camera.
 */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ComponentHealth } from '../../../state/api/types';
import { CameraModelsCard } from '../CameraModelsCard';
import { cameraModelsHeadline, describeProblem, summarizeCameraModels } from '../cameraModelsStatus';

const health = vi.hoisted(() => ({ data: undefined as unknown, admin: false }));
vi.mock('../../../state', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../state')>()),
  useHealthQuery: () => ({ data: health.data }),
  useIsAdmin: () => health.admin,
}));

import { CameraModelsAlert } from '../../navigation/CameraModelsAlert';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const RETIRED = {
  device_id: 'd1', camera: 'THILAKCABIN_OUT_DEMO-CAMERA', model_id: 'geo_fencing', status: 'unavailable' as const,
  in_session: true, reason: 'model_retired', message: 'geo_fencing is retired; use geofence', replacement: 'geofence',
};
const FAILING = {
  device_id: 'd2', camera: 'REFORMER1_OUT_75081', model_id: 'hard_hat', status: 'failing' as const,
  in_session: true, reason: 'inference_failing', message: 'No result for 3 min 10 s: timeout',
  failing_since: '2026-11-19T15:00:00Z', errors: 12,
};
const LEFT_OUT = { ...RETIRED, device_id: 'd3', camera: 'MW01', model_id: 'ppe_detection', in_session: false,
  message: 'ppe_detection is retired' };

function component(problems: unknown[], status: ComponentHealth['status'] = problems.length ? 'degraded' : 'healthy') {
  return {
    status,
    details: { cameras: 3, models: 7, problems,
      failing: problems.filter((p) => (p as { status: string }).status === 'failing').length,
      unavailable: problems.filter((p) => (p as { status: string }).status === 'unavailable').length },
  } as ComponentHealth;
}

describe('summary', () => {
  it('counts and describes problems', () => {
    const s = summarizeCameraModels(component([RETIRED, FAILING, LEFT_OUT]));
    expect([s.reported, s.failing, s.unavailable, s.problems.length]).toEqual([true, 1, 2, 3]);
    expect(cameraModelsHeadline(s)).toBe('3 camera models not working');
    expect(describeProblem(RETIRED)).toBe(
      'THILAKCABIN_OUT_DEMO-CAMERA: geo_fencing not installed — geo_fencing is retired; use geofence');
    expect(describeProblem(FAILING)).toBe('REFORMER1_OUT_75081: hard_hat not running — No result for 3 min 10 s: timeout');
    expect(describeProblem(LEFT_OUT)).toBe('MW01: ppe_detection not installed (saved, not started) — ppe_detection is retired');
  });

  it('an older backend without the component reports nothing', () => {
    expect(summarizeCameraModels(undefined).reported).toBe(false);
  });

  it('a check that could not run says so', () => {
    const s = summarizeCameraModels({ status: 'degraded', error: 'Camera model check failed: TimeoutError' } as ComponentHealth);
    expect(s.error).toBe('Camera model check failed: TimeoutError');
  });
});

describe('rendered', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    health.data = undefined;
    health.admin = false;
  });

  function render(node: React.ReactNode) {
    act(() => root.render(<MemoryRouter>{node}</MemoryRouter>));
  }

  it('the card lists each problem, and is quiet when all run', () => {
    render(<CameraModelsCard component={component([RETIRED, FAILING])} />);
    const card = container.querySelector('[data-testid="camera-models-card"]')!;
    expect(card.className).toContain('camera-models--warn');
    expect(card.textContent).toContain('1 failing, 1 not installed');
    expect(card.querySelectorAll('li')).toHaveLength(2);
    expect(card.textContent).toContain('geo_fencing is retired; use geofence');

    render(<CameraModelsCard component={component([])} />);
    expect(container.textContent).toContain('all 7 running on 3 cameras');
    expect(container.querySelector('.camera-models--ok')).not.toBeNull();

    render(<CameraModelsCard component={undefined} />);
    expect(container.innerHTML).toBe('');
  });

  it('the top-nav alert appears only while something is wrong, and lists it', () => {
    health.data = { status: 'healthy', components: { camera_models: component([]) } };
    render(<CameraModelsAlert />);
    expect(container.innerHTML).toBe('');

    health.data = { status: 'degraded', components: { camera_models: component([RETIRED]) } };
    health.admin = true;
    render(<CameraModelsAlert />);
    const button = container.querySelector('button')!;
    expect(button.textContent).toContain('1 camera model not working');
    act(() => button.click());
    expect(container.querySelector('[role="dialog"]')!.textContent).toContain(
      'THILAKCABIN_OUT_DEMO-CAMERA: geo_fencing not installed');
    expect(container.querySelector('a')!.getAttribute('href')).toBe('/settings/health');
  });
});
