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
import type { ModelLatestNote, ModelStatusInfo } from '../../state/api/types';
import {
  activeModelIds,
  type CameraModelEntry,
  type CameraModelsResponse,
} from '../../state/api/devices.api';
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
  // Zone setup is keyed on "the model has zone rules", not on a model id:
  // an uploaded model with zone types gets the setup button, and enabling
  // it opens the zone editor first.
  const zoneTypes = model.zone_types ?? [];
  // A model whose every rule needs a zone but which names no zone type
  // could never be set up here; the backend refuses it too (422).
  const blockedForZones = model.all_rules_need_zone === true && !isEnabled && zoneTypes.length === 0;
  let state: AIModel['state'];
  if (blockedForZones) {
    state = 'unavailable';
  } else if (model.health === 'unhealthy' || model.status === 'error') {
    state = 'unavailable';
  } else if (model.health === 'degraded') {
    state = isEnabled ? 'degraded' : 'inactive';
  } else if (isEnabled) {
    state = 'active';
  } else {
    state = 'inactive';
  }
  const row: AIModel = {
    id: model.model_id,
    name: model.display_name ?? modelDisplayName(model.model_id),
    state,
    requiresGeofencing: MODELS_REQUIRING_CONFIG.has(model.model_id) || zoneTypes.length > 0,
    pending: isPending,
  };
  if (zoneTypes.length > 0) row.zoneTypes = zoneTypes;
  const recommended = model.recommended_for ?? [];
  if (recommended.length > 0) {
    row.recommendedFor = recommended.map((vt) => violationLabel(model, vt));
  }
  if (model.latest_note) row.note = formatNote(model.latest_note);
  if (blockedForZones) {
    row.disabledReason = `Needs a zone for every rule (${(model.zone_required_rules ?? []).join(', ')}) — available with zone setup`;
  }
  return row;
}

/** "missing_hardhat" -> the server's label, else "Missing hardhat". */
function violationLabel(model: ModelStatusInfo, violationType: string): string {
  const label = model.violation_type_labels?.[violationType];
  if (label) return label;
  const words = violationType.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2026-10-17" -> "17 Oct 2026", without a timezone shifting the day. */
function formatNoteDate(isoDate: string): string {
  const [y, m, d] = isoDate.split('-').map(Number);
  if (!y || !m || !d) return isoDate;
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** A latest note as one line: "17 Oct 2026 · HPCL: Fires on scaffold planks". */
export function formatNote(note: ModelLatestNote): string {
  const when = formatNoteDate(note.observed_on);
  const where = note.project_name ? ` · ${note.project_name}` : '';
  return `${when}${where}: ${note.body}`;
}

/**
 * Recommended models first (stable otherwise), and, on a model that detects
 * something another model is recommended for, a pointer to that model.
 */
function applyRecommendations(rows: AIModel[], available: readonly ModelStatusInfo[]): AIModel[] {
  const recommendedBy = new Map<string, ModelStatusInfo>();
  for (const m of available) {
    for (const vt of m.recommended_for ?? []) recommendedBy.set(vt, m);
  }
  if (recommendedBy.size === 0) return rows;
  const byId = new Map(available.map((m) => [m.model_id, m]));
  for (const row of rows) {
    const model = byId.get(row.id);
    if (!model) continue;
    const pointers = (model.violation_types ?? [])
      .filter((vt) => recommendedBy.has(vt) && recommendedBy.get(vt)!.model_id !== model.model_id)
      .map((vt) => {
        const other = recommendedBy.get(vt)!;
        return `Recommended for ${violationLabel(model, vt)}: ${other.display_name ?? modelDisplayName(other.model_id)}`;
      });
    if (pointers.length > 0) row.alternative = pointers.join(' · ');
  }
  const first = rows.filter((r) => (r.recommendedFor?.length ?? 0) > 0);
  return [...first, ...rows.filter((r) => !first.includes(r))];
}

/**
 * Warning when the built-in PPE model and uploaded PPE models run on the
 * same camera: both report missing PPE, so one missing item raises a
 * violation from each. Null when there is nothing to warn about.
 */
export function ppeOverlapWarning(
  available: readonly ModelStatusInfo[],
  runningIds: readonly string[]
): string | null {
  if (!runningIds.includes('ppe_detection')) return null;
  const overlapping = available.filter(
    (m) => m.source === 'store' && m.reports_ppe === true && runningIds.includes(m.model_id)
  );
  if (overlapping.length === 0) return null;
  const names = overlapping.map((m) => m.display_name ?? modelDisplayName(m.model_id)).join(', ');
  return `PPE Detection and ${names} both report missing PPE: each missing item will raise two violations.`;
}

/**
 * Model ids the camera's saved list holds: the running ones plus saved
 * models a resume left out because they are not installed (`not_started`).
 * A picker Remove acts on any of these.
 */
export function savedModelIdsFor(
  streaming: DeviceStreaming,
  models?: CameraModelsResponse
): string[] {
  const ids = enabledModelIdsFor(streaming, models);
  for (const m of models?.not_started ?? []) {
    if (!ids.includes(m.model_id)) ids.push(m.model_id);
  }
  return ids;
}

/** A model on a camera that is not working: the tile's red chip. */
export interface ModelProblem {
  modelId: string;
  name: string;
  status: 'failing' | 'unavailable';
  message: string;
}

function nameFor(modelId: string, available: readonly ModelStatusInfo[]): string {
  const m = available.find((a) => a.model_id === modelId);
  return m?.display_name ?? modelDisplayName(modelId);
}

function problemMessage(entry: CameraModelEntry): string {
  if (entry.message) return entry.message;
  return entry.status === 'failing' ? 'No result for over a minute' : `${entry.model_id} is not installed`;
}

/**
 * Failing or unavailable models on a camera, from the server's per-camera
 * list (running models first, then saved ones that were not started).
 */
export function modelProblemsFor(
  models: CameraModelsResponse | undefined,
  available: readonly ModelStatusInfo[]
): ModelProblem[] {
  if (!models) return [];
  const out: ModelProblem[] = [];
  for (const entry of [...models.models, ...(models.not_started ?? [])]) {
    if (entry.status === 'failing' || entry.status === 'unavailable') {
      out.push({
        modelId: entry.model_id,
        name: nameFor(entry.model_id, available),
        status: entry.status,
        message: problemMessage(entry),
      });
    }
  }
  return out;
}

/**
 * Picker rows: every healthy or degraded runtime model, then one
 * "unavailable" row with a Remove button for each model the camera runs
 * or has saved that is not installed (retired, or never installed). Those
 * had no row at all before, so they could be neither seen nor removed.
 * A running model that is failing keeps its row, marked degraded, with
 * the reason under it.
 */
export function pickerModels(
  available: ModelStatusInfo[],
  enabledIds: readonly string[],
  pendingModelId?: string | null,
  cameraModels?: CameraModelsResponse
): AIModel[] {
  const usable = available.filter((m) => m.health === 'healthy' || m.health === 'degraded');
  const entries = new Map<string, CameraModelEntry>();
  for (const e of [...(cameraModels?.models ?? []), ...(cameraModels?.not_started ?? [])]) {
    entries.set(e.model_id, e);
  }
  const rows = usable
    .filter((m) => entries.get(m.model_id)?.status !== 'unavailable')
    .map((m) => {
      const row = toAIModel(m, enabledIds.includes(m.model_id), m.model_id === pendingModelId);
      const entry = entries.get(m.model_id);
      if (entry?.status === 'failing' && row.state !== 'unavailable') {
        row.state = 'degraded';
        row.problem = problemMessage(entry);
      }
      return row;
    });
  const ordered = applyRecommendations(rows, usable);
  rows.splice(0, rows.length, ...ordered);
  const listed = new Set(rows.map((r) => r.id));
  const leftovers = [...enabledIds, ...(cameraModels?.not_started ?? []).map((e) => e.model_id)];
  for (const modelId of leftovers) {
    if (listed.has(modelId)) continue;
    listed.add(modelId);
    const entry = entries.get(modelId);
    rows.push({
      id: modelId,
      name: nameFor(modelId, available),
      state: 'unavailable',
      removable: true,
      pending: modelId === pendingModelId,
      disabledReason: entry ? problemMessage(entry) : `${modelId} is not available on this system`,
    });
  }
  return rows;
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
