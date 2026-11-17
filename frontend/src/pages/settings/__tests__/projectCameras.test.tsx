// @vitest-environment jsdom
/**
 * "Cameras in this project" (Settings -> Project) and the rate wording.
 */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CamerasPreflight, ProjectSummary } from '../../admin/adminApi';
import { formatCameraHourRate, formatMonitoredHours, VIOLATIONS_PER_CAMERA_HOUR } from '../../../utils/cameraHours';

const api = vi.hoisted(() => ({
  fetchCamerasPreflight: vi.fn(),
  changeProjectCameras: vi.fn(),
}));
vi.mock('../../admin/adminApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../admin/adminApi')>()),
  ...api,
}));

const { ProjectCamerasCard } = await import('../ProjectCamerasCard');

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement;

const project = (state = 'active') =>
  ({ id: 'p1', name: 'Post HPCL Dev', slug: 'post-hpcl-dev', state, started_at: '2026-11-17T14:48:36Z' }) as ProjectSummary;

const cam = (name: string, enabled: boolean, synced = true) => ({
  name, vas_device_id: `vas-${name}`, device_id: synced ? `dev-${name}` : null, vas_enabled_now: enabled,
  intent: null, intent_models: 0, live_session: false, actions: ['…'], vas_change: false,
});

function preflight(over: Partial<CamerasPreflight> = {}): CamerasPreflight {
  return {
    project: project(),
    allowed: true,
    blocked_reason: null,
    members: [
      { device_id: 'dev-DEMO-CAMERA', vas_device_id: 'vas-DEMO-CAMERA', name: 'DEMO-CAMERA',
        joined_at: '2026-11-17T15:31:03Z', inferred: false, source: 'manual' },
      { device_id: 'dev-75129', vas_device_id: 'vas-75129', name: '75129',
        joined_at: '2026-10-20T06:00:00Z', inferred: true, source: 'derived' },
    ],
    cameras: [cam('74004', true), cam('75129', true), cam('DEMO-CAMERA', true), cam('DEMO-CAMERA2', false)],
    effects: ['Removed cameras … VAS placements (location history) are never changed by this.'],
    ...over,
  };
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  api.fetchCamerasPreflight.mockResolvedValue(preflight());
  api.changeProjectCameras.mockResolvedValue({ id: 'j1', action: 'cameras', state: 'queued' });
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container.remove();
  vi.clearAllMocks();
});

async function render(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root = createRoot(container);
    root.render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
  });
  await flush();
}

const flush = () => act(async () => {
  await new Promise((r) => setTimeout(r, 0));
});
const text = () => container.textContent ?? '';
const button = (prefix: string) =>
  [...container.querySelectorAll('button')].find((b) => b.textContent?.trim().startsWith(prefix))!;
const box = (name: string) => container.querySelector<HTMLInputElement>(`input[aria-label="${name} in project"]`)!;

describe('Cameras in this project', () => {
  it('lists members with since-dates, inferred ones marked', async () => {
    await render(<ProjectCamerasCard project={project()} busy={false} onQueued={() => {}} />);
    expect(text()).toContain('DEMO-CAMERA');
    expect(text()).toContain('75129');
    expect(text()).toMatch(/since .*\(inferred\)/);
  });

  it('flags a camera enabled in VAS but not in the project, and offers to add it', async () => {
    await render(<ProjectCamerasCard project={project()} busy={false} onQueued={() => {}} />);
    expect(text()).toContain('Enabled in VAS but not in this project: 74004');
    await act(async () => button('Add to project').click());
    await flush();
    expect(box('74004').checked).toBe(true);
    expect(button('Confirm').textContent).toBe('Confirm: add 1');
  });

  it('ticks and unticks into add/remove and queues the job', async () => {
    const onQueued = vi.fn();
    await render(<ProjectCamerasCard project={project()} busy={false} onQueued={onQueued} />);
    await act(async () => button('Change cameras').click());
    await flush();
    expect(box('DEMO-CAMERA').checked).toBe(true);
    expect(button('Tick or untick').disabled).toBe(true);
    await act(async () => box('DEMO-CAMERA2').click());
    await act(async () => box('75129').click());
    await flush();
    expect(api.fetchCamerasPreflight).toHaveBeenLastCalledWith(['vas-DEMO-CAMERA2'], ['vas-75129']);
    expect(button('Confirm').textContent).toBe('Confirm: add 1, remove 1');
    await act(async () => button('Confirm').click());
    await flush();
    expect(api.changeProjectCameras).toHaveBeenCalledWith({ add: ['vas-DEMO-CAMERA2'], remove: ['vas-75129'] });
    expect(onQueued).toHaveBeenCalled();
  });

  it('cannot change cameras while stopped or while another action runs', async () => {
    await render(<ProjectCamerasCard project={project('stopped')} busy={false} onQueued={() => {}} />);
    expect(button('Change cameras').disabled).toBe(true);
    expect(text()).toContain('cameras can be changed only while it is active');
    act(() => root?.unmount());
    root = null;
    await render(<ProjectCamerasCard project={project()} busy onQueued={() => {}} />);
    expect(button('Change cameras').disabled).toBe(true);
  });
});

describe('violations per monitored camera-hour', () => {
  it('formats small and large rates, and says when nothing was monitored', () => {
    expect(VIOLATIONS_PER_CAMERA_HOUR).toBe('violations per monitored camera-hour');
    expect(formatCameraHourRate(0.123)).toBe('0.12');
    expect(formatCameraHourRate(2.345)).toBe('2.3');
    expect(formatCameraHourRate(17.6)).toBe('18');
    expect(formatCameraHourRate(null)).toBe('—');
    expect(formatMonitoredHours(0)).toBe('0 h');
    expect(formatMonitoredHours(6)).toBe('6.0 h');
    expect(formatMonitoredHours(4120.4)).toBe('4,120 h');
  });
});
