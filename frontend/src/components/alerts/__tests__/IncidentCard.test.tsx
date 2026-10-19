// @vitest-environment jsdom
/**
 * Incident cards and their actions on the Violations page.
 */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Incident, Violation } from '../../../state/api';
import { IncidentCard } from '../IncidentCard';
import { AlertsList } from '../AlertsList';
import { DEFAULT_FILTERS } from '../AlertsFilterSidebar';

const api = vi.hoisted(() => ({
  fetchIncidents: vi.fn(),
  fetchViolations: vi.fn(),
  updateViolationStatus: vi.fn<(id: string, update: { status?: string }) => Promise<unknown>>(
    async () => ({})
  ),
}));
vi.mock('../../../state/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../state/api')>()),
  ...api,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function violation(over: Partial<Violation> = {}): Violation {
  return {
    id: 'v-latest',
    type: 'ppe_violation',
    type_detail: 'missing_gloves',
    type_label: 'PPE Violation',
    detail_label: 'Missing gloves',
    severity: 'high',
    camera_id: 'cam-1',
    camera_name: '75081',
    camera_display_name: 'REFORMER1_OUT_75081',
    camera_area: 'REFORMER1',
    camera_in_out: 'OUT',
    status: 'open',
    confidence: 0.72,
    timestamp: '2026-10-19T09:31:00Z',
    reviewed_by: null,
    reviewed_at: null,
    created_at: '2026-10-19T09:31:00Z',
    updated_at: '2026-10-19T09:31:00Z',
    evidence: {
      frame_url: '/api/v1/violations/v-latest/frame/image',
      frame_status: 'ready',
      frame_thumb_url: '/api/v1/violations/v-latest/frame/thumb',
      snapshot_id: null,
      snapshot_url: '/snap.jpg',
      snapshot_status: 'ready',
      bookmark_id: null,
      bookmark_url: null,
      bookmark_status: null,
    },
    ...over,
  } as Violation;
}

function incident(over: Partial<Incident> = {}): Incident {
  return {
    incident_id: 'cam-1:missing_gloves:v-first',
    camera_id: 'cam-1',
    camera_name: '75081',
    camera_display_name: 'REFORMER1_OUT_75081',
    camera_area: 'REFORMER1',
    camera_in_out: 'OUT',
    type: 'ppe_violation',
    type_detail: 'missing_gloves',
    type_label: 'PPE Violation',
    detail_label: 'Missing gloves',
    severity: 'critical',
    count: 12,
    open_count: 3,
    first_at: '2026-10-19T09:02:00Z',
    last_at: '2026-10-19T09:31:00Z',
    has_clip: true,
    violation_ids: ['v-latest', 'v2', 'v3', 'v4'],
    open_violation_ids: ['v-latest', 'v2', 'v3'],
    representative: violation(),
    ...over,
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  vi.clearAllMocks();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <MemoryRouter>{node}</MemoryRouter>
      </QueryClientProvider>
    );
  });
}

/** React Query delivers results on a timer, so act() alone doesn't wait for them. */
async function waitFor(check: () => boolean, timeoutMs = 2000) {
  const start = Date.now();
  while (!check()) {
    if (Date.now() - start > timeoutMs) throw new Error('waitFor timed out');
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
  }
}

const button = (text: string) =>
  Array.from(container.querySelectorAll('button')).find((b) => b.textContent?.includes(text));

describe('IncidentCard', () => {
  it('shows camera area · side with its number, the type, count and span', async () => {
    await render(
      <IncidentCard incident={incident()} statuses={['open']} onGroupAction={vi.fn()} onMemberAction={vi.fn()} />
    );
    expect(container.querySelector('.incident-card__camera-name')!.textContent).toBe('REFORMER1 · OUT');
    expect(container.querySelector('.incident-card__camera-number')!.textContent).toBe('#75081');
    expect(container.querySelector('.incident-card__type-detail')!.textContent).toBe('Missing gloves');
    expect(container.textContent).toContain('12 violations · 3 open');
  });

  it('badges severity (not confidence), with no "New" badge while violations are open', async () => {
    await render(
      <IncidentCard incident={incident()} statuses={['open']} onGroupAction={vi.fn()} onMemberAction={vi.fn()} />
    );
    const badge = container.querySelector('.severity-badge')!;
    expect(badge.textContent).toBe('Critical');
    expect(badge.classList.contains('severity-badge--critical')).toBe(true);
    expect(container.querySelector('article')!.classList.contains('incident-card--critical')).toBe(true);
    expect(container.querySelector('.status-badge')).toBeNull();
    expect(container.textContent).not.toContain('New');
    expect(container.textContent).toContain('Latest: Medium confidence'); // secondary text
  });

  it('shows a status badge once nothing in the incident is open', async () => {
    await render(
      <IncidentCard
        incident={incident({ open_count: 0, open_violation_ids: [], representative: violation({ status: 'reviewed' }) })}
        statuses={[]}
        onGroupAction={vi.fn()}
        onMemberAction={vi.fn()}
      />
    );
    expect(container.querySelector('.status-badge')!.textContent).toBe('Reviewed');
    expect(button('Mark')).toBeUndefined();
  });

  it('clip icon only when a clip is ready', async () => {
    await render(
      <IncidentCard incident={incident()} statuses={[]} onGroupAction={vi.fn()} onMemberAction={vi.fn()} />
    );
    expect(container.querySelector('[aria-label="A clip is available"]')).not.toBeNull();
    await render(
      <IncidentCard incident={incident({ has_clip: false })} statuses={[]} onGroupAction={vi.fn()} onMemberAction={vi.fn()} />
    );
    expect(container.querySelector('.incident-card__clip')).toBeNull();
  });

  it('thumbnail is the cropped inferred frame, else the snapshot', async () => {
    await render(
      <IncidentCard incident={incident()} statuses={[]} onGroupAction={vi.fn()} onMemberAction={vi.fn()} />
    );
    expect(container.querySelector('.incident-card__thumb img')!.getAttribute('src')).toBe(
      '/api/v1/violations/v-latest/frame/thumb'
    );
    const noFrame = violation();
    noFrame.evidence = { ...noFrame.evidence!, frame_thumb_url: null, frame_status: null };
    await render(
      <IncidentCard incident={incident({ representative: noFrame })} statuses={[]} onGroupAction={vi.fn()} onMemberAction={vi.fn()} />
    );
    expect(container.querySelector('.incident-card__thumb img')!.getAttribute('src')).toBe('/snap.jpg');
  });

  it('card actions name the open count and go to the group handler', async () => {
    const onGroupAction = vi.fn();
    await render(
      <IncidentCard incident={incident()} statuses={['open']} onGroupAction={onGroupAction} onMemberAction={vi.fn()} />
    );
    await act(async () => button('Dismiss 3')!.click());
    await act(async () => button('Mark 3 reviewed')!.click());
    expect(onGroupAction.mock.calls.map((c) => c[1])).toEqual(['dismiss', 'review']);
  });

  it('expanding lists the members with per-violation actions', async () => {
    api.fetchViolations.mockResolvedValue({
      items: [
        violation({ id: 'v-older', timestamp: '2026-10-19T09:10:00Z' }),
        violation({ id: 'v-done', status: 'reviewed', timestamp: '2026-10-19T09:05:00Z' }),
      ],
      total: 2,
    });
    const onMemberAction = vi.fn();
    await render(
      <IncidentCard incident={incident()} statuses={['open', 'reviewed']} onGroupAction={vi.fn()} onMemberAction={onMemberAction} />
    );
    await act(async () => button('Show all 12')!.click());
    await waitFor(() => container.querySelectorAll('.incident-members__row').length === 2);

    // Fetched with the incident's exact boundaries and the page's statuses.
    expect(api.fetchViolations).toHaveBeenCalledWith(
      expect.objectContaining({
        camera_id: 'cam-1',
        type: 'ppe_violation',
        type_detail: 'missing_gloves',
        since: '2026-10-19T09:02:00Z',
        until: '2026-10-19T09:31:00Z',
        status: ['open', 'reviewed'],
      })
    );
    const rows = container.querySelectorAll('.incident-members__row');
    expect(rows).toHaveLength(2);
    expect(rows[1].querySelector('.status-badge')!.textContent).toBe('Reviewed');
    expect(rows[1].textContent).not.toContain('Dismiss'); // only open rows have actions

    await act(async () => (rows[0].querySelector('.incident-members__action--dismiss') as HTMLButtonElement).click());
    expect(onMemberAction).toHaveBeenCalledWith(
      expect.objectContaining({ incident_id: 'cam-1:missing_gloves:v-first' }),
      expect.objectContaining({ id: 'v-older' }),
      'dismiss'
    );
  });
});

describe('AlertsList group actions', () => {
  it('confirms the open count, then changes exactly those violations', async () => {
    api.fetchIncidents.mockResolvedValue({
      items: [incident()],
      total: 1,
      violations_total: 12,
      gap_minutes: 5,
      max_span_minutes: 60,
    });
    await render(<AlertsList filters={DEFAULT_FILTERS} />);
    await waitFor(() => !!button('Dismiss 3'));
    expect(container.textContent).toContain('1 incident · 12 violations');

    await act(async () => button('Dismiss 3')!.click());
    const dialog = container.querySelector('[role="alertdialog"]')!;
    expect(dialog.textContent).toContain('Dismiss 3 violations?');
    expect(dialog.textContent).toContain('Missing gloves on REFORMER1 · OUT');
    expect(api.updateViolationStatus).not.toHaveBeenCalled();

    await act(async () => button('Yes, dismiss 3')!.click());
    await waitFor(() => api.updateViolationStatus.mock.calls.length === 3);
    const changed = api.updateViolationStatus.mock.calls.map((c) => c[0]).sort();
    expect(changed).toEqual(['v-latest', 'v2', 'v3']); // not v4, already reviewed
    expect(api.updateViolationStatus.mock.calls.every((c) => c[1].status === 'dismissed')).toBe(true);
  });

  it('reports a partial failure on the card', async () => {
    api.fetchIncidents.mockResolvedValue({
      items: [incident()], total: 1, violations_total: 12, gap_minutes: 5, max_span_minutes: 60,
    });
    api.updateViolationStatus.mockImplementation(async (id: string) => {
      if (id === 'v2') throw new Error('409');
      return {};
    });
    await render(<AlertsList filters={DEFAULT_FILTERS} />);
    await waitFor(() => !!button('Mark 3 reviewed'));
    await act(async () => button('Mark 3 reviewed')!.click());
    const confirmButton = Array.from(container.querySelectorAll('[role="alertdialog"] button')).find((b) =>
      b.textContent?.includes('Mark 3 reviewed')
    ) as HTMLButtonElement;
    await act(async () => confirmButton.click());
    await waitFor(() => !!container.querySelector('.incident-card__error'));
    expect(container.querySelector('.incident-card__error')!.textContent).toBe(
      "1 of 3 couldn't be saved. Please try again."
    );
  });
});
