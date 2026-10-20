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
import { DEFAULT_FILTERS } from '../alertFilters';

const api = vi.hoisted(() => ({
  fetchIncidents: vi.fn(),
  fetchViolations: vi.fn(),
  updateViolationStatus: vi.fn(),
  bulkUpdateViolations: vi.fn(),
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
      <IncidentCard incident={incident()} statuses={['open']} onGroupAction={vi.fn()} onMemberAction={vi.fn()} expanded={false} onToggleExpand={vi.fn()} />
    );
    expect(container.querySelector('.incident-card__camera-name')!.textContent).toBe('REFORMER1 · OUT');
    expect(container.querySelector('.incident-card__camera-number')!.textContent).toBe('#75081');
    expect(container.querySelector('.incident-card__type-detail')!.textContent).toBe('Missing gloves');
    expect(container.textContent).toContain('12 violations · 3 open');
  });

  it('badges severity (not confidence), with no "New" badge while violations are open', async () => {
    await render(
      <IncidentCard incident={incident()} statuses={['open']} onGroupAction={vi.fn()} onMemberAction={vi.fn()} expanded={false} onToggleExpand={vi.fn()} />
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
        expanded={false}
        onToggleExpand={vi.fn()}
      />
    );
    expect(container.querySelector('.status-badge')!.textContent).toBe('Reviewed');
    expect(button('Mark')).toBeUndefined();
  });

  it('clip icon only when a clip is ready', async () => {
    await render(
      <IncidentCard incident={incident()} statuses={[]} onGroupAction={vi.fn()} onMemberAction={vi.fn()} expanded={false} onToggleExpand={vi.fn()} />
    );
    expect(container.querySelector('[aria-label="A clip is available"]')).not.toBeNull();
    await render(
      <IncidentCard incident={incident({ has_clip: false })} statuses={[]} onGroupAction={vi.fn()} onMemberAction={vi.fn()} expanded={false} onToggleExpand={vi.fn()} />
    );
    expect(container.querySelector('.incident-card__clip')).toBeNull();
  });

  it('thumbnail is the cropped inferred frame, else the snapshot', async () => {
    await render(
      <IncidentCard incident={incident()} statuses={[]} onGroupAction={vi.fn()} onMemberAction={vi.fn()} expanded={false} onToggleExpand={vi.fn()} />
    );
    expect(container.querySelector('.incident-card__thumb img')!.getAttribute('src')).toBe(
      '/api/v1/violations/v-latest/frame/thumb'
    );
    const noFrame = violation();
    noFrame.evidence = { ...noFrame.evidence!, frame_thumb_url: null, frame_status: null };
    await render(
      <IncidentCard incident={incident({ representative: noFrame })} statuses={[]} onGroupAction={vi.fn()} onMemberAction={vi.fn()} expanded={false} onToggleExpand={vi.fn()} />
    );
    expect(container.querySelector('.incident-card__thumb img')!.getAttribute('src')).toBe('/snap.jpg');
  });

  it('card actions name the open count and go to the group handler', async () => {
    const onGroupAction = vi.fn();
    await render(
      <IncidentCard incident={incident()} statuses={['open']} onGroupAction={onGroupAction} onMemberAction={vi.fn()} expanded={false} onToggleExpand={vi.fn()} />
    );
    await act(async () => button('Dismiss 3')!.click());
    await act(async () => button('Mark 3 reviewed')!.click());
    expect(onGroupAction.mock.calls.map((c) => c[1])).toEqual(['dismiss', 'review']);
  });

  it('expanding asks the page, and an expanded card lists its members with row actions', async () => {
    api.fetchViolations.mockResolvedValue({
      items: [
        violation({ id: 'v-older', timestamp: '2026-10-19T09:10:00Z' }),
        violation({ id: 'v-done', status: 'reviewed', timestamp: '2026-10-19T09:05:00Z' }),
      ],
      total: 2,
    });
    const onToggleExpand = vi.fn();
    await render(
      <IncidentCard incident={incident()} statuses={['open']} onGroupAction={vi.fn()} onMemberAction={vi.fn()}
        expanded={false} onToggleExpand={onToggleExpand} />
    );
    await act(async () => button('Show all 12')!.click());
    expect(onToggleExpand).toHaveBeenCalledWith(expect.objectContaining({ incident_id: 'cam-1:missing_gloves:v-first' }));

    const onMemberAction = vi.fn();
    await render(
      <IncidentCard incident={incident()} statuses={['open', 'reviewed']} onGroupAction={vi.fn()}
        onMemberAction={onMemberAction} expanded onToggleExpand={vi.fn()} />
    );
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
    expect(rows[1].querySelector('.status-badge')!.textContent).toBe('Reviewed');
    expect(rows[1].textContent).not.toContain('Dismiss'); // only open rows have actions
    await act(async () => (rows[0].querySelector('.incident-members__action--dismiss') as HTMLButtonElement).click());
    expect(onMemberAction).toHaveBeenCalledWith(
      expect.objectContaining({ incident_id: 'cam-1:missing_gloves:v-first' }),
      expect.objectContaining({ id: 'v-older' }),
      'dismiss'
    );
  });

  it('a selection checkbox only while something is open', async () => {
    const onToggleSelect = vi.fn();
    await render(
      <IncidentCard incident={incident()} statuses={[]} onGroupAction={vi.fn()} onMemberAction={vi.fn()}
        expanded={false} onToggleExpand={vi.fn()} selected={false} onToggleSelect={onToggleSelect} />
    );
    await act(async () => (container.querySelector('.incident-card__select input') as HTMLInputElement).click());
    expect(onToggleSelect).toHaveBeenCalled();
    await render(
      <IncidentCard incident={incident({ open_count: 0, open_violation_ids: [] })} statuses={[]}
        onGroupAction={vi.fn()} onMemberAction={vi.fn()} expanded={false} onToggleExpand={vi.fn()}
        onToggleSelect={onToggleSelect} />
    );
    expect(container.querySelector('.incident-card__select input')).toBeNull();
  });
});

const SUMMARY = {
  open_violations: 12,
  violations_by_severity: { critical: 12, high: 0, medium: 0, low: 0 },
  incidents_by_severity: { critical: 2, high: 0, medium: 0, low: 0 },
  cameras: 2,
  top_area: 'REFORMER1',
  top_area_violations: 9,
};

function listResponse(items: Incident[]) {
  return { items, total: items.length, violations_total: 12, gap_minutes: 5, max_span_minutes: 60, summary: SUMMARY };
}

function renderList(over: Partial<React.ComponentProps<typeof AlertsList>> = {}) {
  return render(
    <AlertsList
      filters={DEFAULT_FILTERS}
      page={1}
      pageSize={10}
      expanded={null}
      onPageChange={vi.fn()}
      onPageSizeChange={vi.fn()}
      onToggleExpand={vi.fn()}
      {...over}
    />
  );
}

const dialog = () => container.querySelector('[role="alertdialog"]');
const dialogButton = (text: string) =>
  Array.from(dialog()?.querySelectorAll('button') ?? []).find((b) => b.textContent?.includes(text)) as
    | HTMLButtonElement
    | undefined;

async function chooseReason(label: string) {
  const option = Array.from(dialog()!.querySelectorAll('label')).find((l) => l.textContent?.includes(label))!;
  await act(async () => (option.querySelector('input') as HTMLInputElement).click());
}

describe('AlertsList actions go through POST /violations/bulk', () => {
  beforeEach(() => {
    api.bulkUpdateViolations.mockResolvedValue({
      updated: ['v-latest', 'v2', 'v3'],
      skipped: [],
      labelling: { exported: 3, no_frame: 0, failed: 0, capped: 0 },
    });
  });

  it('shows the summary strip for the current filters', async () => {
    api.fetchIncidents.mockResolvedValue(listResponse([incident()]));
    await renderList();
    await waitFor(() => !!container.querySelector('.summary-strip'));
    const strip = container.querySelector('.summary-strip')!.textContent!;
    expect(strip).toContain('Incidents1');
    expect(strip).toContain('Open12');
    expect(strip).toContain('Critical2');
    expect(strip).toContain('REFORMER1');
    expect(strip).toContain('Last 7 days · repeats within 5 min');
  });

  it('card Dismiss asks for a reason and sends one bulk request for the open ids', async () => {
    api.fetchIncidents.mockResolvedValue(listResponse([incident()]));
    await renderList();
    await waitFor(() => !!button('Dismiss 3'));
    await act(async () => button('Dismiss 3')!.click());

    expect(dialog()!.textContent).toContain('Dismiss 3 violations');
    expect(dialog()!.textContent).toContain('Missing gloves on REFORMER1 · OUT');
    expect(dialogButton('Dismiss 3')!.disabled).toBe(true); // no reason yet

    await chooseReason('PPE actually worn');
    expect(dialog()!.textContent).toContain('copied to the labelling set');
    await act(async () => dialogButton('Dismiss 3')!.click());
    await waitFor(() => api.bulkUpdateViolations.mock.calls.length === 1);

    expect(api.bulkUpdateViolations).toHaveBeenCalledWith({
      ids: ['v-latest', 'v2', 'v3'], // not v4: already reviewed
      action: 'dismiss',
      dismiss_reason: 'ppe_worn',
      note: undefined,
    });
    expect(api.updateViolationStatus).not.toHaveBeenCalled(); // no per-violation calls any more
    await waitFor(() => !!container.textContent?.includes('3 frames sent to labelling'));
  });

  it('"Other false alarm" needs a note', async () => {
    api.fetchIncidents.mockResolvedValue(listResponse([incident()]));
    await renderList();
    await waitFor(() => !!button('Dismiss 3'));
    await act(async () => button('Dismiss 3')!.click());
    await chooseReason('Other false alarm');
    expect(dialogButton('Dismiss 3')!.disabled).toBe(true);
    const note = dialog()!.querySelector('textarea')!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
      setter.call(note, 'reflective tape');
      note.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(dialogButton('Dismiss 3')!.disabled).toBe(false);
    await act(async () => dialogButton('Dismiss 3')!.click());
    await waitFor(() => api.bulkUpdateViolations.mock.calls.length === 1);
    expect(api.bulkUpdateViolations.mock.calls[0][0]).toMatchObject({
      dismiss_reason: 'other_false_alarm',
      note: 'reflective tape',
    });
  });

  it('Mark reviewed confirms the count and reports skips on the card', async () => {
    api.fetchIncidents.mockResolvedValue(listResponse([incident()]));
    api.bulkUpdateViolations.mockResolvedValue({
      updated: ['v-latest', 'v3'],
      skipped: [{ id: 'v2', reason: 'invalid_transition', status: 'dismissed' }],
      labelling: null,
    });
    await renderList();
    await waitFor(() => !!button('Mark 3 reviewed'));
    await act(async () => button('Mark 3 reviewed')!.click());
    expect(dialog()!.textContent).toContain('Mark 3 violations reviewed?');
    await act(async () => dialogButton('Mark 3 reviewed')!.click());
    await waitFor(() => !!container.querySelector('.incident-card__error'));
    expect(api.bulkUpdateViolations.mock.calls[0][0]).toEqual({
      ids: ['v-latest', 'v2', 'v3'], action: 'review', dismiss_reason: undefined, note: undefined,
    });
    expect(container.querySelector('.incident-card__error')!.textContent).toContain('1 of 3 were already');
  });

  it('bulk select: select page, then one request for every selected open violation', async () => {
    const second = incident({
      incident_id: 'cam-2:missing_vest:x1',
      camera_id: 'cam-2',
      open_count: 2,
      open_violation_ids: ['x1', 'x2'],
      violation_ids: ['x1', 'x2'],
    });
    const closed = incident({ incident_id: 'closed', open_count: 0, open_violation_ids: [] });
    api.fetchIncidents.mockResolvedValue(listResponse([incident(), second, closed]));
    await renderList();
    await waitFor(() => !!container.querySelector('.alerts-list__bulk'));

    const selectPage = container.querySelector('.alerts-list__bulk-select input') as HTMLInputElement;
    await act(async () => selectPage.click());
    // All three, including the fully-reviewed one: the evidence export
    // covers reviewed and dismissed incidents, so they have to be
    // selectable. The open-violation count is what the bulk actions use,
    // and the closed incident contributes none.
    expect(container.querySelector('.alerts-list__bulk-count')!.textContent).toBe('3 incidents · 5 open violations');
    expect(container.querySelectorAll('.incident-card--selected')).toHaveLength(3);

    await act(async () => button('Dismiss…')!.click());
    expect(dialog()!.textContent).toContain('Dismiss 5 violations');
    await chooseReason('Pipework / object');
    await act(async () => dialogButton('Dismiss 5')!.click());
    await waitFor(() => api.bulkUpdateViolations.mock.calls.length === 1);
    expect(api.bulkUpdateViolations.mock.calls[0][0]).toMatchObject({
      ids: ['v-latest', 'v2', 'v3', 'x1', 'x2'],
      action: 'dismiss',
      dismiss_reason: 'object',
    });
    // Selection clears after a bulk action.
    await waitFor(() => !container.querySelector('.alerts-list__bulk-count'));
  });

  it('bulk review and dismiss are disabled when nothing open is selected', async () => {
    // Selecting a fully-reviewed incident is allowed (for the export), but
    // acting on it would be a no-op request, so the actions are blocked.
    const closed = incident({ incident_id: 'closed', open_count: 0, open_violation_ids: [] });
    api.fetchIncidents.mockResolvedValue(listResponse([closed]));
    await renderList();
    await waitFor(() => !!container.querySelector('.alerts-list__bulk'));

    const selectPage = container.querySelector('.alerts-list__bulk-select input') as HTMLInputElement;
    await act(async () => selectPage.click());
    expect(container.querySelector('.alerts-list__bulk-count')!.textContent).toBe('1 incident · 0 open violations');
    expect((button('Mark reviewed') as HTMLButtonElement).disabled).toBe(true);
    expect((button('Dismiss…') as HTMLButtonElement).disabled).toBe(true);
    // The export is still offered.
    expect(button('Download snapshots…')).toBeTruthy();
  });

  it('expanding is delegated to the page (URL state)', async () => {
    api.fetchIncidents.mockResolvedValue(listResponse([incident()]));
    const onToggleExpand = vi.fn();
    await renderList({ onToggleExpand });
    await waitFor(() => !!button('Show all 12'));
    await act(async () => button('Show all 12')!.click());
    expect(onToggleExpand).toHaveBeenCalledWith('cam-1:missing_gloves:v-first');
  });
});
