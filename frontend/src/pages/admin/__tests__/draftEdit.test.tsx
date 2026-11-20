// @vitest-environment jsdom
/**
 * Editing a draft's display name and model ID (17 Nov: "harness3" was
 * uploaded off the naming standard and the only fix was delete + re-upload).
 */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminApiError, type StoreModelDetail } from '../adminApi';
import { modelIdFromName, modelIdProblem } from '../modelIds';

const api = vi.hoisted(() => ({ updateStoreModel: vi.fn() }));
vi.mock('../adminApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../adminApi')>()),
  ...api,
}));

const { DraftEditForm } = await import('../DraftEditForm');

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

function draft(over: Partial<StoreModelDetail> = {}): StoreModelDetail {
  return {
    id: 'pk1', model_id: 'harness3', display_name: 'harness3', state: 'draft',
    model_id_editable: true, file_count: 1, total_bytes: 66_060_288, status: 'uploaded',
    created_at: '2026-11-17T05:58:59Z', created_by: 'admin', runtime: null,
    files: [], active_uploads: [], ...over,
  };
}

async function render(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root = createRoot(container);
    root.render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
  });
}

const inputs = () => Array.from(container.querySelectorAll('input'));
const button = (label: string) =>
  Array.from(container.querySelectorAll('button')).find((b) => b.textContent?.startsWith(label))!;

async function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function click(el: HTMLElement) {
  await act(async () => {
    el.click();
    await new Promise((r) => setTimeout(r, 0));
  });
}

describe('model ID rules (mirror of the backend)', () => {
  it.each(['Harness3', 'harness 3', 'harness-3', '3harness', 'hx', 'ppe_detection', 'test_harness'])(
    'refuses %s',
    (id) => expect(modelIdProblem(id)).not.toBeNull()
  );
  it.each(['harness3', 'harness_v3', 'safety_vest'])('accepts %s', (id) =>
    expect(modelIdProblem(id)).toBeNull()
  );
  it('derives the same ID the backend generates', () => {
    expect(modelIdFromName('PPE — six items')).toBe('ppe_six_items');
    expect(modelIdFromName('Harness V3')).toBe('harness_v3');
    expect(modelIdFromName('3D Harness')).toBe('model_3d_harness');
    expect(modelIdFromName('Test rig')).toBe('model_test_rig');
    expect(modelIdFromName('ab')).toBe('ab_model');
  });
});

describe('DraftEditForm', () => {
  it('renames display name and ID in one save, sending only what changed', async () => {
    const saved = draft({ display_name: 'Harness v3', model_id: 'harness_v3' });
    api.updateStoreModel.mockResolvedValue(saved);
    const onSaved = vi.fn();
    await render(<DraftEditForm model={draft()} onSaved={onSaved} onCancel={vi.fn()} />);

    const [name, id] = inputs();
    await type(name, 'Harness v3');
    await click(button('Use "harness_v3"'));
    expect(id.value).toBe('harness_v3');
    await click(button('Save'));

    expect(api.updateStoreModel).toHaveBeenCalledWith('pk1', {
      display_name: 'Harness v3',
      model_id: 'harness_v3',
    });
    expect(onSaved).toHaveBeenCalledWith(saved);
  });

  it('explains an off-standard ID and will not save it', async () => {
    await render(<DraftEditForm model={draft()} onSaved={vi.fn()} onCancel={vi.fn()} />);
    await type(inputs()[1], 'Harness 3');
    expect(container.textContent).toContain('no capitals, spaces or hyphens');
    expect(button('Save').disabled).toBe(true);
  });

  it('saves nothing until something changes; blank name is refused', async () => {
    await render(<DraftEditForm model={draft()} onSaved={vi.fn()} onCancel={vi.fn()} />);
    expect(button('Save').disabled).toBe(true);
    await type(inputs()[0], '   ');
    expect(container.textContent).toContain('Display name is required');
    expect(button('Save').disabled).toBe(true);
  });

  it('locks the ID of an installed model but still renames it', async () => {
    api.updateStoreModel.mockResolvedValue(draft());
    await render(
      <DraftEditForm
        model={draft({ model_id: 'harness', display_name: 'Harness', model_id_editable: false })}
        onSaved={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    const [name, id] = inputs();
    expect(id.disabled).toBe(true);
    expect(container.textContent).toContain('Locked: this model is installed');
    await type(name, 'Harness (full body)');
    await click(button('Save'));
    expect(api.updateStoreModel).toHaveBeenCalledWith('pk1', { display_name: 'Harness (full body)' });
  });

  it('shows the server refusal (e.g. ID already used)', async () => {
    api.updateStoreModel.mockRejectedValue(
      new AdminApiError(409, "model_id 'harness_v3' is already used (or was used)")
    );
    await render(<DraftEditForm model={draft()} onSaved={vi.fn()} onCancel={vi.fn()} />);
    await type(inputs()[1], 'harness_v3');
    await click(button('Save'));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('already used');
  });
});
