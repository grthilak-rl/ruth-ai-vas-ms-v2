// @vitest-environment jsdom
/**
 * Notes and the recommended flag on a model's page: dated notes with
 * project, source, internal switch; one of a model's notes as the reason it
 * is recommended for a violation type.
 */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ModelNote, ModelRecommendation, StoreModelDetail } from '../adminApi';

const api = vi.hoisted(() => ({
  listModelNotes: vi.fn(),
  createModelNote: vi.fn(),
  updateModelNote: vi.fn(),
  deleteModelNote: vi.fn(),
  listProjects: vi.fn(),
  listRecommendations: vi.fn(),
  setRecommendation: vi.fn(),
  clearRecommendation: vi.fn(),
}));
vi.mock('../adminApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../adminApi')>()),
  ...api,
}));

const { ModelNotesSection, ModelRecommendationSection } = await import('../ModelNotes');

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  api.listProjects.mockResolvedValue({ items: [{ id: 'p1', name: 'HPCL' }, { id: 'p2', name: 'Post HPCL Dev' }], active: null });
  api.listRecommendations.mockResolvedValue([]);
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
    id: 'pk1', model_id: 'hard_hat', display_name: 'Hard Hat', state: 'draft', model_id_editable: false,
    installed: true, violation_types: ['missing_hardhat'], recommended_for: [], file_count: 1,
    total_bytes: 1, status: 'uploaded', created_at: '2026-10-04T05:00:00Z', created_by: 'admin',
    runtime: null, files: [], active_uploads: [], ...over,
  };
}

function note(over: Partial<ModelNote> = {}): ModelNote {
  return {
    id: 'n1', model_pk: 'pk1', observed_on: '2026-10-17', body: 'Inconclusive: 0 fires on 32 frames',
    project_id: 'p1', project_name: 'HPCL', source: '/mnt/storage/ruth-models/eval/2026-10-17/README.md',
    internal: false, created_by: 'imported', created_at: '2026-11-20T08:00:00Z', edited_by: null,
    updated_at: '2026-11-20T08:00:00Z', reason_for: [], ...over,
  };
}

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

const button = (label: string) =>
  Array.from(container.querySelectorAll('button')).find((b) => b.textContent?.trim() === label)!;

async function click(el: HTMLElement) {
  await act(async () => {
    el.click();
    await new Promise((r) => setTimeout(r, 0));
  });
}

async function setValue(el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
    : el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')!.set!;
  await act(async () => {
    setter.call(el, value);
    el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
  });
}

describe('notes on the model page', () => {
  it('lists notes with date, project, author, source and tags', async () => {
    api.listModelNotes.mockResolvedValue([
      note({ id: 'n2', observed_on: '2026-11-01', body: 'Site check', internal: true, project_name: null, source: null }),
      note({ reason_for: ['missing_hardhat'] }),
    ]);
    await render(<ModelNotesSection model={model()} />);

    const items = container.querySelectorAll('.model-notes__item');
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain('1 Nov 2026');
    expect(items[0].textContent).toContain('Internal');
    expect(items[1].textContent).toContain('17 Oct 2026 · HPCL · imported');
    expect(items[1].textContent).toContain('Recommendation reason');
    expect(items[1].textContent).toContain('Source: /mnt/storage/ruth-models/eval/2026-10-17/README.md');
    // The reason for a recommendation cannot be deleted from here.
    const deletes = Array.from(container.querySelectorAll('button')).filter((b) => b.textContent === 'Delete');
    expect(deletes.map((b) => b.disabled)).toEqual([false, true]);
  });

  it('adds a note with project, source and the internal switch', async () => {
    api.listModelNotes.mockResolvedValue([]);
    api.createModelNote.mockResolvedValue(note());
    await render(<ModelNotesSection model={model()} />);
    await click(button('Add note'));

    const form = container.querySelector('form[aria-label="Add note"]')!;
    await setValue(form.querySelector('input[type="date"]') as HTMLInputElement, '2026-11-18');
    await setValue(form.querySelector('select') as HTMLSelectElement, 'p2');
    await setValue(form.querySelector('textarea') as HTMLTextAreaElement, '  Fires on scaffold planks  ');
    await setValue(form.querySelectorAll('input:not([type])')[0] as HTMLInputElement, 'violation 1234');
    await click(form.querySelector('input[type="checkbox"]') as HTMLInputElement);
    await click(button('Save note'));

    expect(api.createModelNote).toHaveBeenCalledWith('pk1', {
      body: 'Fires on scaffold planks', observed_on: '2026-11-18', project_id: 'p2',
      source: 'violation 1234', internal: true,
    });
  });
});

describe('recommending a model', () => {
  it('recommends this model for its violation type with a chosen note as the reason', async () => {
    api.listModelNotes.mockResolvedValue([note()]);
    api.setRecommendation.mockResolvedValue([]);
    await render(<ModelRecommendationSection model={model()} />);

    expect(container.textContent).toContain('No model is recommended for this yet.');
    await click(button('Recommend this model'));
    expect(button('Recommend').disabled).toBe(true); // a reason is required
    await setValue(container.querySelector('select') as HTMLSelectElement, 'n1');
    await click(button('Recommend'));
    expect(api.setRecommendation).toHaveBeenCalledWith('missing_hardhat', 'pk1', 'n1');
  });

  it('shows the current recommendation and lets it be cleared', async () => {
    const rec: ModelRecommendation = {
      violation_type: 'missing_hardhat', label: 'Missing hard hat', model_pk: 'pk1', model_id: 'hard_hat',
      display_name: 'Hard Hat', active: true, note: note(), set_by: 'imported', set_at: '2026-11-20T08:00:00Z',
    };
    api.listRecommendations.mockResolvedValue([rec]);
    api.listModelNotes.mockResolvedValue([note()]);
    api.clearRecommendation.mockResolvedValue(undefined);
    await render(<ModelRecommendationSection model={model({ recommended_for: ['missing_hardhat'] })} />);

    expect(container.textContent).toContain('Missing hard hat');
    expect(container.textContent).toContain('This model is recommended. Reason (17 Oct 2026): Inconclusive');
    await click(button('Stop recommending'));
    expect(api.clearRecommendation).toHaveBeenCalledWith('missing_hardhat');
  });

  it("names another model's recommendation, and says when that model is not installed", async () => {
    api.listRecommendations.mockResolvedValue([{
      violation_type: 'missing_goggles', label: 'Missing goggles', model_pk: 'other', model_id: 'goggles_3',
      display_name: 'Goggles 3', active: false, note: note({ model_pk: 'other' }), set_by: 'imported',
      set_at: '2026-11-20T08:00:00Z',
    }]);
    api.listModelNotes.mockResolvedValue([]);
    await render(<ModelRecommendationSection model={model({ model_id: 'no_goggles', violation_types: ['missing_goggles'] })} />);
    expect(container.textContent).toContain('Goggles 3 is recommended (not installed, so not shown).');
    expect(button('Recommend this model instead')).toBeTruthy();
  });

  it('asks for an install first when the model is not installed', async () => {
    api.listModelNotes.mockResolvedValue([]);
    await render(<ModelRecommendationSection model={model({ installed: false, violation_types: [] })} />);
    expect(container.textContent).toContain('Install the model to recommend it.');
  });
});
