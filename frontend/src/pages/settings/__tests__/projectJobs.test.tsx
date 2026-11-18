// @vitest-environment jsdom
/**
 * Project actions as background jobs, in the Project tab:
 * - the progress card shows each stage, the one running and its detail,
 *   and offers Retry from the stage that failed or was interrupted;
 * - the Start form cannot start a project with no cameras by accident
 *   (17 Nov: Post HPCL Dev started with none because nothing was ticked).
 */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProjectJob } from '../../admin/adminApi';
import { ProjectJobProgress } from '../ProjectJobProgress';

const api = vi.hoisted(() => ({
  fetchStartPreflight: vi.fn(),
  startNextProject: vi.fn(),
}));
vi.mock('../../admin/adminApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../admin/adminApi')>()),
  ...api,
}));

const { StartNextProject } = await import('../SettingsProjectTab');

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
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
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

function job(over: Partial<ProjectJob>): ProjectJob {
  return {
    id: 'j1', action: 'start', state: 'running', stage: 'cameras', stage_detail: 'DEMO-CAMERA2 (2/3)',
    stages: [
      { key: 'backup', label: 'Back up the database', status: 'done' },
      { key: 'project', label: 'Create the project', status: 'done' },
      { key: 'cameras', label: 'Switch cameras in VAS', status: 'running' },
    ],
    error_code: null, error_message: null, errors: [], cameras: [], retention_paused: null,
    project_id: 'p1', project_name: 'Post HPCL Dev', backup_path: '/b/x.dump', attempts: 1,
    can_retry: false, created_by: 'admin', created_at: '2026-11-17T15:00:00Z',
    started_at: '2026-11-17T15:00:00Z', finished_at: null,
    ...over,
  };
}

const text = () => container.textContent ?? '';

describe('ProjectJobProgress', () => {
  it('shows the running stage and its detail, and no buttons while running', async () => {
    await render(<ProjectJobProgress job={job({})} onRetry={() => {}} retrying={false} onDismiss={() => {}} />);
    expect(text()).toContain('Starting Post HPCL Dev…');
    expect(text()).toContain('Switch cameras in VAS');
    expect(text()).toContain('DEMO-CAMERA2 (2/3)');
    expect(container.querySelector('.project-job__stage--running')?.textContent).toContain('Switch cameras');
    expect(container.querySelectorAll('button')).toHaveLength(0);
  });

  it('offers Retry from the interrupted stage', async () => {
    const onRetry = vi.fn();
    const cut = job({
      state: 'interrupted', can_retry: true, error_code: 'interrupted',
      error_message: 'The backend restarted during "Switch cameras in VAS". Retry continues from there.',
      stages: [
        { key: 'backup', label: 'Back up the database', status: 'done' },
        { key: 'project', label: 'Create the project', status: 'done' },
        { key: 'cameras', label: 'Switch cameras in VAS', status: 'interrupted' },
      ],
    });
    await render(<ProjectJobProgress job={cut} onRetry={onRetry} retrying={false} onDismiss={() => {}} />);
    expect(text()).toContain('was interrupted');
    expect(text()).toContain('The backend restarted during');
    const retry = [...container.querySelectorAll('button')].find((b) => b.textContent?.startsWith('Retry'));
    expect(retry?.textContent).toBe('Retry from “Switch cameras in VAS”');
    await act(async () => retry!.click());
    expect(onRetry).toHaveBeenCalled();
  });

  it('names the cameras VAS would not switch', async () => {
    const failed = job({
      state: 'failed', can_retry: true, error_code: 'incomplete',
      error_message: 'DEMO-CAMERA3: VAS did not enable it (timeout)',
      errors: ['DEMO-CAMERA3: VAS did not enable it (timeout)'],
    });
    await render(<ProjectJobProgress job={failed} onRetry={() => {}} retrying={false} onDismiss={() => {}} />);
    expect(text()).toContain('did not finish');
    expect(text()).toContain('DEMO-CAMERA3: VAS did not enable it');
  });

  it('says what changed when it succeeded', async () => {
    const ok = job({
      state: 'succeeded', stage_detail: null, retention_paused: true,
      stages: job({}).stages.map((s) => ({ ...s, status: 'done' as const })),
      cameras: [1, 2, 3].map((i) => ({
        name: `DEMO-CAMERA${i}`, vas_device_id: `v${i}`, device_id: `d${i}`, vas_enabled_now: false,
        intent: null, intent_models: 0, live_session: false, actions: [], vas_change: true,
      })),
    });
    await render(<ProjectJobProgress job={ok} onRetry={() => {}} retrying={false} onDismiss={() => {}} />);
    expect(text()).toContain('Post HPCL Dev is now the current project');
    expect(text()).toContain('3 cameras changed in VAS');
    expect(text()).toContain('Footage deletion pause: on');
  });
});

describe('Start the next project', () => {
  const cams = ['DEMO-CAMERA', 'DEMO-CAMERA2'].map((n) => ({
    name: n, vas_device_id: `vas-${n}`, device_id: `dev-${n}`, vas_enabled_now: false,
    intent: null, intent_models: 0, live_session: false, actions: ['Stays disabled'], vas_change: false,
  }));

  beforeEach(() => {
    api.fetchStartPreflight.mockResolvedValue({
      can_proceed: true, blocked_reason: null, blockers: [], current_project: null, last_project: null,
      cameras: cams, backup_dir: '/var/backups/ruth-ai', effects: [],
    });
    api.startNextProject.mockResolvedValue(job({ state: 'queued' }));
  });

  async function typeName(name: string) {
    const inputs = container.querySelectorAll<HTMLInputElement>('input[type="text"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    for (const input of inputs) {
      await act(async () => {
        setter.call(input, name);
        input.dispatchEvent(new Event('input', { bubbles: true }));
      });
    }
  }

  const submit = () => container.querySelector<HTMLButtonElement>('button[type="submit"]')!;
  const box = (label: string) =>
    container.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;

  it('picks no camera by default and will not start without one', async () => {
    await render(<StartNextProject last={null} busy={false} onQueued={() => {}} />);
    await typeName('Post HPCL Dev');
    expect(box('Run DEMO-CAMERA').checked).toBe(false);
    expect(submit().disabled).toBe(true);
    expect(text()).toContain('Tick the cameras this project runs, or confirm starting with no cameras.');
  });

  it('starts with the ticked cameras', async () => {
    const onQueued = vi.fn();
    await render(<StartNextProject last={null} busy={false} onQueued={onQueued} />);
    await typeName('Post HPCL Dev');
    await act(async () => box('Run DEMO-CAMERA').click());
    await act(async () => box('Run DEMO-CAMERA2').click());
    expect(submit().textContent).toBe('Start “Post HPCL Dev” with 2 cameras');
    await act(async () => submit().click());
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(api.startNextProject).toHaveBeenCalledWith({
      name: 'Post HPCL Dev', confirm_name: 'Post HPCL Dev',
      camera_ids: ['vas-DEMO-CAMERA', 'vas-DEMO-CAMERA2'], allow_no_cameras: false,
    });
    expect(onQueued).toHaveBeenCalled();
  });

  it('starts with no cameras only when that is confirmed', async () => {
    await render(<StartNextProject last={null} busy={false} onQueued={() => {}} />);
    await typeName('Empty Project');
    const confirm = container.querySelector<HTMLInputElement>('.start-project__no-cameras input')!;
    await act(async () => confirm.click());
    expect(submit().disabled).toBe(false);
    await act(async () => submit().click());
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(api.startNextProject).toHaveBeenCalledWith(
      expect.objectContaining({ camera_ids: [], allow_no_cameras: true })
    );
  });

  it('is disabled while another project action runs', async () => {
    await render(<StartNextProject last={null} busy onQueued={() => {}} />);
    await typeName('Post HPCL Dev');
    await act(async () => box('Run DEMO-CAMERA').click());
    expect(submit().disabled).toBe(true);
    expect(text()).toContain('Another project action is running');
  });
});
