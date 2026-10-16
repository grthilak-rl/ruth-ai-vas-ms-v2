/**
 * Store runtime visibility on the System Health view.
 *
 * The backend reports `degraded` for BOTH "unreachable" and "reachable but
 * some models not ready", so that an unreachable store cannot flip overall
 * system health to unhealthy. These tests pin the frontend side of that
 * split: unreachable has to read as a hard failure (red) with the error and
 * the last-success time, which is precisely what was missing while the
 * store sat broken for twelve days.
 */

import { describe, it, expect } from 'vitest';
import type { ComponentHealth } from '../../../state';
import {
  storeRuntimeIsUnreachable,
  getModelStoreDescription,
  deriveStoreRuntimeStatus,
} from '../storeRuntimeStatus';

const reachable = (overrides: Record<string, unknown> = {}): ComponentHealth =>
  ({
    status: 'healthy',
    latency_ms: 12,
    details: {
      configured: true,
      reachable: true,
      runtime_id: 'model-store-runtime',
      url: 'http://model-store-runtime:8000',
      models_ready: 3,
      models_total: 3,
      models_loaded: ['gloves', 'hard_hat', 'safety_vest'],
      ...overrides,
    },
  }) as ComponentHealth;

const unreachable = (): ComponentHealth =>
  ({
    status: 'degraded',
    latency_ms: 203,
    error: 'Failed to connect: [Errno -2] Name or service not known',
    details: {
      configured: true,
      reachable: false,
      runtime_id: 'model-store-runtime',
      url: 'http://model-store-runtime:8000',
      models_ready: 0,
      models_total: 0,
      last_success_at: new Date(Date.now() - 3 * 60 * 1000).toISOString(),
    },
  }) as ComponentHealth;

describe('storeRuntimeIsUnreachable', () => {
  it('is true only when the last check failed', () => {
    expect(storeRuntimeIsUnreachable(unreachable())).toBe(true);
    expect(storeRuntimeIsUnreachable(reachable())).toBe(false);
  });

  it('is false when absent or disabled, never a false alarm', () => {
    expect(storeRuntimeIsUnreachable(undefined)).toBe(false);
    expect(
      storeRuntimeIsUnreachable({ status: 'disabled' } as ComponentHealth)
    ).toBe(false);
  });
});

describe('deriveStoreRuntimeStatus', () => {
  it('renders unreachable red even though the backend says degraded', () => {
    // The backend deliberately reports `degraded` so overall health does
    // not go unhealthy; the card still has to look like a failure.
    const component = unreachable();
    expect(component.status).toBe('degraded');
    expect(deriveStoreRuntimeStatus(component)).toBe('offline');
  });

  it('keeps a reachable-but-partial store amber', () => {
    const component = reachable({
      models_ready: 2,
      models_total: 3,
      models_not_ready: ['gloves'],
    });
    component.status = 'degraded';
    expect(deriveStoreRuntimeStatus(component)).toBe('degraded');
  });

  it('is healthy when everything is loaded', () => {
    expect(deriveStoreRuntimeStatus(reachable())).toBe('healthy');
  });

  it('is disabled when the store is not configured', () => {
    expect(
      deriveStoreRuntimeStatus({
        status: 'disabled',
        details: { configured: false },
      } as ComponentHealth)
    ).toBe('disabled');
  });
});

describe('getModelStoreDescription', () => {
  it('names the failure and when it last worked', () => {
    const component = unreachable();
    const text = getModelStoreDescription('offline', component);

    expect(text).toContain('Unreachable');
    expect(text).toContain('Name or service not known');
    // Process-local, so it must be labelled as such rather than implying
    // durable history across restarts.
    expect(text).toContain('since backend start');
    expect(text).toContain('3 minutes ago');
    expect(text).toContain('Uploaded models are unavailable');
  });

  it('says so when it has never been reachable in this process', () => {
    const component = unreachable();
    delete (component.details as Record<string, unknown>).last_success_at;
    expect(getModelStoreDescription('offline', component)).toContain(
      'Not reachable since this backend started'
    );
  });

  it('lists which models are not loaded when partially ready', () => {
    const component = reachable({
      models_ready: 2,
      models_total: 3,
      models_not_ready: ['gloves'],
    });
    const text = getModelStoreDescription('degraded', component);

    expect(text).toContain('2 of 3');
    expect(text).toContain('Not loaded: gloves');
  });

  it('reports the ready count when healthy', () => {
    expect(getModelStoreDescription('healthy', reachable())).toBe(
      '3 of 3 uploaded models ready.'
    );
  });
});
