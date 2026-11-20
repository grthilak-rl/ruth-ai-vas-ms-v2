// @vitest-environment jsdom
/**
 * "Delete draft" on an installed model would trash the files the store
 * runtime runs from (every installed model is still a draft). The page
 * disables both deletes and says why; the server refuses regardless.
 */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminApiError, type StoreModelDetail } from '../adminApi';

const api = vi.hoisted(() => ({
  getStoreModel: vi.fn(),
  deleteStoreModel: vi.fn(),
  deleteStoreFile: vi.fn(),
  // The page's notes and recommendation sections; not under test here.
  listModelNotes: vi.fn(async () => []),
  listProjects: vi.fn(async () => ({ items: [], active: null })),
  listRecommendations: vi.fn(async () => []),
}));
vi.mock('../adminApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../adminApi')>()),
  ...api,
}));

const { ModelDetailPage } = await import('../ModelDetailPage');

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container.remove();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

function model(over: Partial<StoreModelDetail> = {}): StoreModelDetail {
  return {
    id: 'pk1', model_id: 'hard_hat', display_name: 'Hard Hat', state: 'draft',
    model_id_editable: false, installed: true, file_count: 1, total_bytes: 6_000_000,
    status: 'uploaded', created_at: '2026-10-04T05:00:00Z', created_by: 'admin', runtime: null,
    files: [{ id: 'f1', filename: 'besthardhat.pt', size_bytes: 6_000_000, sha256: 'ab'.repeat(32),
      uploaded_at: '2026-10-04T05:00:00Z', uploaded_by: 'admin', status: 'uploaded' }],
    active_uploads: [], ...over,
  };
}

async function render() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root = createRoot(container);
    root.render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/settings/models/pk1']}>
          <Routes>
            <Route path="/settings/models/:modelPk" element={<ModelDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

const button = (label: string) =>
  Array.from(container.querySelectorAll('button')).find((b) => b.textContent?.trim() === label)!;

describe('Delete on an installed model', () => {
  it('disables Delete draft and file Delete, and says why', async () => {
    api.getStoreModel.mockResolvedValue(model());
    await render();

    expect(button('Delete draft').disabled).toBe(true);
    expect(button('Delete').disabled).toBe(true);
    expect(button('Delete draft').title).toContain('Uninstall it before deleting');
    expect(container.querySelector('[role="note"]')?.textContent).toContain(
      'the model store runtime is using its files'
    );
  });

  it('leaves both enabled for a draft that is not installed', async () => {
    api.getStoreModel.mockResolvedValue(model({ model_id: 'harness_3', installed: false, model_id_editable: true }));
    await render();

    expect(button('Delete draft').disabled).toBe(false);
    expect(button('Delete').disabled).toBe(false);
    expect(container.querySelector('[role="note"]')).toBeNull();
  });

  it("shows the server's refusal when the page was loaded before the install", async () => {
    api.getStoreModel.mockResolvedValue(model({ installed: false }));
    api.deleteStoreModel.mockRejectedValue(
      new AdminApiError(
        409,
        "Cannot delete this draft: 'hard_hat' is installed and its files are in use by the model store runtime. Uninstall the model first."
      )
    );
    await render();
    await act(async () => {
      button('Delete draft').click();
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "'hard_hat' is installed and its files are in use"
    );
  });
});
