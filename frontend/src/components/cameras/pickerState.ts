/**
 * Camera picker state, derived from the server.
 *
 * The picker shows what the backend says runs on a camera — never a local
 * guess — and every toggle becomes one call on /devices/{id}/models:
 *   - tick a model     -> POST   /devices/{id}/models          (starts inference if none)
 *   - untick a model   -> DELETE /devices/{id}/models/{model}  (others keep running;
 *                                                               removing the last stops)
 *   - edit its config  -> PATCH  /devices/{id}/models/{model}
 *
 * Pure functions so the rules can be tested without rendering.
 */

import type { AIModel } from './AIModelSelector';
import type { DeviceStreaming } from '../../state/api/types';
import type { ModelStatusInfo } from '../../state/api/types';
import { activeModelIds, type CameraModelsResponse } from '../../state/api/devices.api';
import type { ModelConfig } from '../../types/geofencing';

/** Models whose picker row has a setup button (zones / tank corners). */
const MODELS_REQUIRING_CONFIG = new Set(['tank_overflow_monitoring', 'geo_fencing']);

/** "fall_detection" -> "Fall Detection"; "*_container" -> "... (Legacy)". */
export function modelDisplayName(modelId: string): string {
  let name = modelId
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
  if (modelId.includes('_container')) {
    name = name.replace(' Container', ' (Legacy)');
  }
  return name;
}

/**
 * Model ids running on the camera. The per-camera models list wins when it
 * has been fetched (it is refreshed on every change and when the picker
 * opens); otherwise the devices list's streaming summary.
 */
export function enabledModelIdsFor(
  streaming: DeviceStreaming,
  models?: CameraModelsResponse
): string[] {
  if (models) return models.models.map((m) => m.model_id);
  return activeModelIds(streaming);
}

/** Each running model's config, keyed by model id. */
export function configsFor(
  streaming: DeviceStreaming,
  models?: CameraModelsResponse
): Record<string, ModelConfig> {
  const out: Record<string, ModelConfig> = {};
  if (models) {
    for (const m of models.models) {
      if (m.config) out[m.model_id] = m.config;
    }
    return out;
  }
  // Before the list is fetched only the primary model's config is known.
  if (streaming.ai_enabled && streaming.model_id && streaming.model_config) {
    out[streaming.model_id] = streaming.model_config as ModelConfig;
  }
  return out;
}

/** A runtime model as a picker row. */
export function toAIModel(model: ModelStatusInfo, isEnabled: boolean, isPending: boolean = false): AIModel {
  let state: AIModel['state'];
  if (model.health === 'unhealthy' || model.status === 'error') {
    state = 'unavailable';
  } else if (model.health === 'degraded') {
    state = isEnabled ? 'degraded' : 'inactive';
  } else if (isEnabled) {
    state = 'active';
  } else {
    state = 'inactive';
  }
  return {
    id: model.model_id,
    name: modelDisplayName(model.model_id),
    state,
    requiresGeofencing: MODELS_REQUIRING_CONFIG.has(model.model_id),
    pending: isPending,
  };
}

/** Picker rows: every healthy or degraded runtime model. */
export function pickerModels(
  available: ModelStatusInfo[],
  enabledIds: readonly string[],
  pendingModelId?: string | null
): AIModel[] {
  return available
    .filter((m) => m.health === 'healthy' || m.health === 'degraded')
    .map((m) => toAIModel(m, enabledIds.includes(m.model_id), m.model_id === pendingModelId));
}

export type ToggleAction =
  | { kind: 'add'; entry: { model_id: string; config?: ModelConfig } }
  | { kind: 'update'; changes: { config: ModelConfig } }
  | { kind: 'remove' }
  | { kind: 'noop' };

/**
 * What a picker toggle means on the server.
 *
 * `config` arrives with a toggle when the setup modal was saved: on a
 * running model that is a config change, on a stopped one it is the
 * config to start it with.
 */
export function planToggle(
  enable: boolean,
  modelId: string,
  runningIds: readonly string[],
  config?: ModelConfig
): ToggleAction {
  const running = runningIds.includes(modelId);
  if (enable) {
    if (running) return config ? { kind: 'update', changes: { config } } : { kind: 'noop' };
    return { kind: 'add', entry: config ? { model_id: modelId, config } : { model_id: modelId } };
  }
  return running ? { kind: 'remove' } : { kind: 'noop' };
}

export interface ToggleCalls {
  add: (entry: { model_id: string; config?: ModelConfig }) => Promise<unknown>;
  update: (changes: { config: ModelConfig }) => Promise<unknown>;
  remove: () => Promise<unknown>;
}

/** Carry out a planned toggle: exactly one call, never a camera-wide stop. */
export async function executeToggle(action: ToggleAction, calls: ToggleCalls): Promise<void> {
  switch (action.kind) {
    case 'add':
      await calls.add(action.entry);
      return;
    case 'update':
      await calls.update(action.changes);
      return;
    case 'remove':
      await calls.remove();
      return;
    case 'noop':
      return;
  }
}
