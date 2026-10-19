// @vitest-environment jsdom
/**
 * The Violations list keeps its state across a visit to a violation:
 * filters, page and page size come from the URL (Back, refresh, shared
 * links), and the scroll position is restored.
 */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AlertsPage } from '../AlertsPage';
import { saveScrollPosition } from '../../utils/alertsListMemory';

const api = vi.hoisted(() => ({
  fetchIncidents: vi.fn(),
  fetchDevices: vi.fn(async () => ({
    items: [
      { id: 'cam-1', name: '75081', display_name: 'REFORMER1_OUT_75081', manway: 'REFORMER1', in_out: 'OUT' },
    ],
    total: 1,
  })),
  fetchViolationTypes: vi.fn(async () => ({ items: [] })),
}));
vi.mock('../../state/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../state/api')>()),
  ...api,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let router: ReturnType<typeof createMemoryRouter>;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  sessionStorage.clear();
  localStorage.clear();
  vi.clearAllMocks();
  api.fetchIncidents.mockResolvedValue({
    items: [], total: 0, violations_total: 0, gap_minutes: 5, max_span_minutes: 60,
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function waitFor(check: () => boolean, timeoutMs = 2000) {
  const start = Date.now();
  while (!check()) {
    if (Date.now() - start > timeoutMs) throw new Error('waitFor timed out');
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
  }
}

async function renderAt(url: string) {
  router = createMemoryRouter([{ path: '/alerts', element: <AlertsPage /> }], { initialEntries: [url] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    );
  });
}

const lastQuery = () => api.fetchIncidents.mock.calls.at(-1)![0];

describe('Alerts page URL state', () => {
  it('reads filters, page and page size from the URL', async () => {
    await renderAt('/alerts?status=any&range=all&severity=critical&area=REFORMER1&page=3&per_page=25');
    await waitFor(() => api.fetchIncidents.mock.calls.length > 0);
    expect(lastQuery()).toMatchObject({ severity: ['critical'], area: 'REFORMER1', offset: 50, limit: 25 });
    expect(lastQuery().status).toBeUndefined();
    expect(lastQuery().since).toBeUndefined(); // all time
  });

  it('defaults to open violations from the last 7 days', async () => {
    await renderAt('/alerts');
    await waitFor(() => api.fetchIncidents.mock.calls.length > 0);
    expect(lastQuery().status).toEqual(['open']);
    const since = new Date(lastQuery().since).getTime();
    expect(Math.abs(Date.now() - 7 * 86_400_000 - since)).toBeLessThan(120_000);
  });

  it('a filter change goes into the URL and back to page 1', async () => {
    await renderAt('/alerts?page=4');
    await waitFor(() => !!container.querySelector('input[type="checkbox"]'));
    const critical = Array.from(container.querySelectorAll('label')).find((l) => l.textContent === 'Critical')!;
    await act(async () => (critical.querySelector('input') as HTMLInputElement).click());
    expect(router.state.location.search).toBe('?severity=critical');
    await waitFor(() => lastQuery().offset === 0);
    expect(sessionStorage.getItem('ruth-ai-alerts-list-search')).toBe('severity=critical');
  });

  it('restores the scroll position saved for this list URL', async () => {
    saveScrollPosition('range=30d', 640);
    await renderAt('/alerts?range=30d');
    const main = container.querySelector('.alerts-page__main') as HTMLElement;
    await waitFor(() => main.scrollTop === 640);
  });
});
