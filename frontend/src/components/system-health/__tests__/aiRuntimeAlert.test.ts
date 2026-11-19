/**
 * GPU / AI Runtime outage visibility (24 Aug GPU outage).
 *
 * The backend reports the AI Runtime `unhealthy` when the GPU is missing or
 * the runtime does not answer. These tests pin that both get a red banner
 * on System Health and a red top-bar indicator (not the old yellow
 * "Degraded").
 */

import { describe, it, expect } from 'vitest';
import { getAIRuntimeAlert } from '../aiRuntimeStatus';
import { deriveGlobalStatus, getGlobalStatusDisplay } from '../../../state/hooks/useHealthQuery';
import type { HealthResponse } from '../../../state';

describe('getAIRuntimeAlert', () => {
  it('is null when the AI Runtime is healthy or degraded', () => {
    expect(getAIRuntimeAlert(undefined)).toBeNull();
    expect(getAIRuntimeAlert({ status: 'healthy' })).toBeNull();
    expect(getAIRuntimeAlert({ status: 'degraded', error: 'Models running on CPU' })).toBeNull();
  });

  it('names the GPU when the GPU is missing', () => {
    const alert = getAIRuntimeAlert({
      status: 'unhealthy',
      error: 'GPU unavailable - AI inference is not running on the GPU',
      details: { reachable: true, gpu_expected: true, gpu_available: false, gpu_reason: 'CUDA not available' },
    });
    expect(alert?.title).toMatch(/GPU not available/);
    expect(alert?.detail).toMatch(/CUDA not available/);
    expect(alert?.detail).toMatch(/nvidia-smi/);
  });

  it('is equally loud when the runtime is unreachable', () => {
    const alert = getAIRuntimeAlert({
      status: 'unhealthy',
      error: 'AI Runtime unreachable: ConnectError',
      details: { reachable: false },
    });
    expect(alert?.title).toMatch(/AI detection is DOWN - AI Runtime unreachable/);
    expect(alert?.detail).toBe('AI Runtime unreachable: ConnectError');
  });

  it('does not blame the GPU on a CPU deployment', () => {
    const alert = getAIRuntimeAlert({
      status: 'unhealthy',
      error: 'AI Runtime unhealthy',
      details: { reachable: true, gpu_expected: false, gpu_available: false },
    });
    expect(alert?.title).not.toMatch(/GPU/);
  });
});

describe('deriveGlobalStatus', () => {
  const health = (status: string) => ({ status }) as unknown as HealthResponse;

  it('maps backend unhealthy to a red "System Fault", not yellow "Degraded"', () => {
    expect(deriveGlobalStatus(health('unhealthy'), false)).toBe('unhealthy');
    expect(getGlobalStatusDisplay('unhealthy')).toBe('System Fault');
  });

  it('keeps healthy, degraded and offline as before', () => {
    expect(deriveGlobalStatus(health('healthy'), false)).toBe('healthy');
    expect(deriveGlobalStatus(health('degraded'), false)).toBe('degraded');
    expect(deriveGlobalStatus(undefined, true)).toBe('offline');
  });
});
