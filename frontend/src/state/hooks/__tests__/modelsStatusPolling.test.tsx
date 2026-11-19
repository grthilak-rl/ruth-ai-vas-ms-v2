// @vitest-environment jsdom
/**
 * The Cameras page reads the installed-model list from the shared hook:
 * polled every 30 s and refetched on focus, so a tab left open across a
 * deploy stops offering retired models.
 */

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { POLLING_INTERVALS } from '../../pollingIntervals';
import { queryKeys } from '../../queryKeys';

vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api')>()),
  fetchModelsStatus: vi.fn(async () => ({ models: [] })),
}));

import { useModelsStatusQuery } from '../useModelsStatusQuery';
import { cameraModelsQueryOptions } from '../useDevicesQuery';
import dashboardSource from '../../../components/cameras/CameraMonitoringDashboard.tsx?raw';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function Probe() {
  useModelsStatusQuery();
  return null;
}

describe('model list polling', () => {
  it('the installed-model list is polled every 30 s and refetched on focus', async () => {
    expect(POLLING_INTERVALS.MODELS_STATUS).toBe(30_000);
    const client = new QueryClient();
    const container = document.createElement('div');
    const root = createRoot(container);
    await act(async () => root.render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>));
    const query = client.getQueryCache().find({ queryKey: queryKeys.models.status });
    const options = query?.options as { refetchInterval?: number; refetchOnWindowFocus?: boolean };
    expect(options.refetchInterval).toBe(30_000);
    expect(options.refetchOnWindowFocus).not.toBe(false);
    act(() => root.unmount());
  });

  it("each camera's model list (with statuses) is polled every 30 s", () => {
    expect(cameraModelsQueryOptions('d1').refetchInterval).toBe(30_000);
  });

  it('the Cameras page uses the shared hook, not a one-off fetch', () => {
    expect(dashboardSource).toContain('useModelsStatusQuery()');
    expect(dashboardSource).not.toContain('fetchModelsStatus(');
  });
});
