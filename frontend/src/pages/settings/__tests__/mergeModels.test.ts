import { describe, expect, it } from 'vitest';
import {
  mergeModels,
  UPLOADED_STATE_LABEL,
  type MergeInput,
} from '../mergeModels';
import type { ModelStatusInfo, StoreRuntimeStatus } from '../../../state/api/types';
import type { StoreModelSummary } from '../../admin/adminApi';

/**
 * The merge is a union, never an inner join. Each test below pins one of
 * the four states an uploaded model can be in, because each corresponds to
 * a real situation an operator has to be able to tell apart — and because
 * an inner join would silently drop two of them.
 */

function statusEntry(overrides: Partial<ModelStatusInfo> = {}): ModelStatusInfo {
  return {
    model_id: 'fall_detection',
    version: '1.0.0',
    status: 'idle',
    health: 'healthy',
    cameras_active: 0,
    last_inference_at: null,
    started_at: null,
    ...overrides,
  };
}

function storeEntry(overrides: Partial<StoreModelSummary> = {}): StoreModelSummary {
  return {
    id: 'pk-1',
    model_id: 'ppe_six',
    display_name: 'PPE six items',
    state: 'draft',
    model_id_editable: true,
    file_count: 4,
    total_bytes: 1024,
    status: 'uploaded',
    created_at: '2026-10-01T00:00:00Z',
    created_by: 'admin',
    ...overrides,
  };
}

const reachable: StoreRuntimeStatus = { reachable: true };
const unreachable: StoreRuntimeStatus = { reachable: false, error: 'timeout' };

function merge(input: Partial<MergeInput> = {}) {
  return mergeModels({ statusModels: [], ...input });
}

// ---------------------------------------------------------------------------
// Separation of the two groups
// ---------------------------------------------------------------------------

describe('built-in vs uploaded', () => {
  it('splits on source === "store"', () => {
    const result = merge({
      statusModels: [
        statusEntry({ model_id: 'fall_detection' }),
        statusEntry({ model_id: 'ppe_six', source: 'store' }),
      ],
      storeRuntime: reachable,
    });

    expect(result.builtIn.map((m) => m.model_id)).toEqual(['fall_detection']);
    expect(result.uploaded.map((m) => m.model_id)).toEqual(['ppe_six']);
  });

  it('treats a missing source field as built-in', () => {
    const result = merge({ statusModels: [statusEntry()] });
    expect(result.builtIn).toHaveLength(1);
    expect(result.uploaded).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// The four uploaded states
// ---------------------------------------------------------------------------

describe('uploaded model states', () => {
  it('in both sources -> installed', () => {
    const result = merge({
      statusModels: [statusEntry({ model_id: 'ppe_six', source: 'store' })],
      storeRuntime: reachable,
      storeModels: [storeEntry()],
    });

    expect(result.uploaded).toHaveLength(1);
    expect(result.uploaded[0].uploadedState).toBe('installed');
    expect(result.uploaded[0].status).toBeDefined();
    expect(result.uploaded[0].store).toBeDefined();
  });

  it('upload record only -> not installed (and is NOT dropped)', () => {
    const result = merge({
      statusModels: [],
      storeRuntime: reachable,
      storeModels: [storeEntry()],
    });

    expect(result.uploaded).toHaveLength(1);
    expect(result.uploaded[0].uploadedState).toBe('not_installed');
    expect(result.uploaded[0].status).toBeUndefined();
  });

  it('runtime entry only, admin list present -> installed outside Model Management', () => {
    // storeModels: [] (not undefined) means we asked and the answer was
    // "no upload rows". Only then is the stronger label earned.
    const result = merge({
      statusModels: [statusEntry({ model_id: 'cli_model', source: 'store' })],
      storeRuntime: reachable,
      storeModels: [],
    });

    expect(result.uploaded).toHaveLength(1);
    expect(result.uploaded[0].uploadedState).toBe('installed_outside_management');
    expect(result.uploaded[0].store).toBeUndefined();
  });

  it('unreachable runtime -> runtime unreachable for rows it cannot confirm', () => {
    const result = merge({
      statusModels: [],
      storeRuntime: unreachable,
      storeModels: [storeEntry()],
    });

    expect(result.uploaded[0].uploadedState).toBe('runtime_unreachable');
    expect(result.runtimeUnreachable).toBe(true);
  });

  it('does not downgrade a model the runtime actually reported', () => {
    // Direct evidence beats a stale unreachable flag: if the status list
    // contains the model, something answered for it.
    const result = merge({
      statusModels: [statusEntry({ model_id: 'ppe_six', source: 'store' })],
      storeRuntime: unreachable,
      storeModels: [storeEntry()],
    });

    expect(result.uploaded[0].uploadedState).toBe('installed');
  });
});

// ---------------------------------------------------------------------------
// Signed out
// ---------------------------------------------------------------------------

describe('signed out (no admin rows)', () => {
  it('labels a running uploaded model neutrally as installed', () => {
    const result = merge({
      statusModels: [statusEntry({ model_id: 'ppe_six', source: 'store' })],
      storeRuntime: reachable,
      storeModels: undefined,
    });

    expect(result.uploaded).toHaveLength(1);
    // Signed out we never fetched the admin list, so "no upload row" is
    // our own blindness, not a fact. Claiming "installed outside Model
    // Management" would accuse the deployment of an irregularity on the
    // strength of a request we did not make. Neutral "Installed" is true
    // and is all the open endpoint supports.
    expect(result.uploaded[0].uploadedState).toBe('installed');
    expect(result.uploaded[0].store).toBeUndefined();
  });

  it('is the same model, labelled differently once the admin list loads', () => {
    // The distinction is about evidence, not about the model: identical
    // status input, and only the presence of the admin list changes the
    // verdict. This is the pair the fix turns on.
    const statusModels = [statusEntry({ model_id: 'cli_model', source: 'store' })];

    const signedOut = merge({ statusModels, storeRuntime: reachable });
    const signedIn = merge({ statusModels, storeRuntime: reachable, storeModels: [] });

    expect(signedOut.uploaded[0].uploadedState).toBe('installed');
    expect(signedIn.uploaded[0].uploadedState).toBe('installed_outside_management');
  });

  it('cannot see uploads that were never installed', () => {
    // Nothing to do about this: the only source for them is admin-only.
    // The list is smaller, never wrong.
    const result = merge({
      statusModels: [],
      storeRuntime: reachable,
      storeModels: undefined,
    });
    expect(result.uploaded).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Naming
// ---------------------------------------------------------------------------

describe('display names', () => {
  it('prefers the upload record name over the manifest name', () => {
    const result = merge({
      statusModels: [
        statusEntry({
          model_id: 'ppe_six',
          source: 'store',
          display_name: 'Stale manifest name',
        }),
      ],
      storeRuntime: reachable,
      storeModels: [storeEntry({ display_name: 'PPE six items' })],
    });

    expect(result.uploaded[0].displayName).toBe('PPE six items');
  });

  it('falls back to the manifest name when signed out', () => {
    const result = merge({
      statusModels: [
        statusEntry({ model_id: 'ppe_six', source: 'store', display_name: 'PPE six items' }),
      ],
      storeRuntime: reachable,
    });

    expect(result.uploaded[0].displayName).toBe('PPE six items');
  });

  it('humanizes the id only as a last resort', () => {
    const result = merge({ statusModels: [statusEntry({ model_id: 'fall_detection' })] });
    expect(result.builtIn[0].displayName).toBe('Fall Detection');
  });
});

// ---------------------------------------------------------------------------
// Store runtime configuration
// ---------------------------------------------------------------------------

describe('store runtime configuration', () => {
  it('distinguishes "not configured" from "unreachable"', () => {
    const notConfigured = merge({ statusModels: [statusEntry()] });
    expect(notConfigured.storeRuntimeConfigured).toBe(false);
    expect(notConfigured.runtimeUnreachable).toBe(false);

    const down = merge({ statusModels: [statusEntry()], storeRuntime: unreachable });
    expect(down.storeRuntimeConfigured).toBe(true);
    expect(down.runtimeUnreachable).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Keys and ordering
// ---------------------------------------------------------------------------

describe('keys and ordering', () => {
  it('gives every row a unique key across both groups', () => {
    const result = merge({
      statusModels: [
        statusEntry({ model_id: 'fall_detection' }),
        statusEntry({ model_id: 'ppe_six', source: 'store' }),
      ],
      storeRuntime: reachable,
      storeModels: [storeEntry(), storeEntry({ id: 'pk-2', model_id: 'other', display_name: 'Other' })],
    });

    const keys = [...result.builtIn, ...result.uploaded].map((m) => m.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('sorts each group by display name', () => {
    const result = merge({
      statusModels: [
        statusEntry({ model_id: 'zebra_model' }),
        statusEntry({ model_id: 'alpha_model' }),
      ],
    });
    expect(result.builtIn.map((m) => m.displayName)).toEqual([
      'Alpha Model',
      'Zebra Model',
    ]);
  });

  it('never duplicates a model present in both sources', () => {
    const result = merge({
      statusModels: [statusEntry({ model_id: 'ppe_six', source: 'store' })],
      storeRuntime: reachable,
      storeModels: [storeEntry({ model_id: 'ppe_six' })],
    });
    expect(result.uploaded).toHaveLength(1);
  });
});

describe('labels', () => {
  it('has a label for every state', () => {
    expect(Object.keys(UPLOADED_STATE_LABEL).sort()).toEqual([
      'installed',
      'installed_outside_management',
      'not_installed',
      'runtime_unreachable',
    ]);
  });
});
