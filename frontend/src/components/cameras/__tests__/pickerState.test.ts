/**
 * Camera picker (M3): server state in, one /devices/{id}/models call out.
 */

import { describe, expect, it, vi } from 'vitest';
import type { AIModel } from '../AIModelSelector';
import type { DeviceStreaming, ModelStatusInfo } from '../../../state/api/types';
import type { CameraModelsResponse } from '../../../state/api/devices.api';
import {
  configsFor,
  enabledModelIdsFor,
  executeToggle,
  modelDisplayName,
  modelProblemsFor,
  pickerModels,
  planToggle,
  ppeOverlapWarning,
  savedModelIdsFor,
  toAIModel,
  type ToggleAction,
} from '../pickerState';

function streaming(over: Partial<DeviceStreaming> = {}): DeviceStreaming {
  return {
    active: true,
    ai_enabled: false,
    model_id: null,
    model_config: null,
    ...over,
  } as DeviceStreaming;
}

function modelsResponse(entries: Array<{ model_id: string; config?: Record<string, unknown> | null }>): CameraModelsResponse {
  return {
    device_id: 'd1',
    session_id: entries.length ? 's1' : null,
    models_revision: entries.length,
    models: entries.map((e) => ({
      model_id: e.model_id,
      model_version: null,
      config: (e.config ?? null) as CameraModelsResponse['models'][number]['config'],
      fps_override: null,
      target_fps: 2,
    })),
  };
}

function status(model_id: string, health: string = 'healthy', st: string = 'active'): ModelStatusInfo {
  return { model_id, health, status: st } as unknown as ModelStatusInfo;
}

describe('which models run on a camera', () => {
  it('the per-camera models list wins over the devices list', () => {
    const s = streaming({ ai_enabled: true, model_id: 'fall_detection', models: ['fall_detection'] });
    const fresh = modelsResponse([{ model_id: 'fall_detection' }, { model_id: 'ppe_detection' }]);
    expect(enabledModelIdsFor(s, fresh)).toEqual(['fall_detection', 'ppe_detection']);
  });

  it('an empty fetched list means nothing runs, whatever the devices list says', () => {
    const s = streaming({ ai_enabled: true, model_id: 'fall_detection' });
    expect(enabledModelIdsFor(s, modelsResponse([]))).toEqual([]);
  });

  it('falls back to the devices list before the models list is fetched', () => {
    expect(enabledModelIdsFor(streaming())).toEqual([]);
    expect(enabledModelIdsFor(streaming({ ai_enabled: true, model_id: 'fall_detection' }))).toEqual([
      'fall_detection',
    ]);
    expect(
      enabledModelIdsFor(
        streaming({ ai_enabled: true, model_id: 'fall_detection', models: ['fall_detection', 'geo_fencing'] })
      )
    ).toEqual(['fall_detection', 'geo_fencing']);
  });

  it('configs come per model from the list, or the primary only before it', () => {
    const zones = { zones: [{ id: 'z1' }] };
    const roi = { roi_circle: { cx: 1, cy: 2, r: 3 } };
    const fresh = modelsResponse([
      { model_id: 'fall_detection' },
      { model_id: 'geo_fencing', config: zones },
      { model_id: 'chane_tank_monitor', config: roi },
    ]);
    expect(configsFor(streaming(), fresh)).toEqual({ geo_fencing: zones, chane_tank_monitor: roi });
    expect(
      configsFor(streaming({ ai_enabled: true, model_id: 'geo_fencing', model_config: zones }))
    ).toEqual({ geo_fencing: zones });
    expect(configsFor(streaming({ ai_enabled: false, model_id: 'geo_fencing', model_config: zones }))).toEqual({});
  });
});

describe('picker rows', () => {
  /** The dashboard's convertToAIModel before M3, verbatim apart from the toggle lookup. */
  function legacyConvert(model: ModelStatusInfo, isEnabled: boolean): AIModel {
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
    let displayName = model.model_id
      .split('_')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
    if (model.model_id.includes('_container')) {
      displayName = displayName.replace(' Container', ' (Legacy)');
    }
    const requiresGeofencing = model.model_id === 'tank_overflow_monitoring' || model.model_id === 'geo_fencing';
    return { id: model.model_id, name: displayName, state, requiresGeofencing };
  }

  const cases: ModelStatusInfo[] = [
    status('fall_detection'),
    status('ppe_detection', 'degraded'),
    status('geo_fencing', 'unhealthy'),
    status('tank_overflow_monitoring', 'healthy', 'error'),
    status('chane_tank_monitor'),
    status('fall_detection_container'),
  ];

  it('look exactly as before for every health and enabled combination', () => {
    for (const m of cases) {
      for (const enabled of [true, false]) {
        const { pending, ...row } = toAIModel(m, enabled);
        expect(pending).toBe(false);
        expect(row).toEqual(legacyConvert(m, enabled));
      }
    }
  });

  it('list healthy and degraded models, ticked from server state, one pending', () => {
    const rows = pickerModels(cases, ['fall_detection', 'ppe_detection'], 'ppe_detection');
    expect(rows.map((r) => r.id)).toEqual(['fall_detection', 'ppe_detection', 'tank_overflow_monitoring', 'chane_tank_monitor', 'fall_detection_container']);
    expect(rows.find((r) => r.id === 'fall_detection')).toMatchObject({ state: 'active', pending: false });
    expect(rows.find((r) => r.id === 'ppe_detection')).toMatchObject({ state: 'degraded', pending: true });
    expect(rows.find((r) => r.id === 'chane_tank_monitor')).toMatchObject({ state: 'inactive' });
  });

  it('display names', () => {
    expect(modelDisplayName('ppe_detection')).toBe('Ppe Detection');
    expect(modelDisplayName('fall_detection_container')).toBe('Fall Detection (Legacy)');
  });
});

describe('what a toggle does on the server', () => {
  const zones = { zones: [{ id: 'z1' }] } as never;

  it.each<[string, boolean, string, string[], unknown, ToggleAction]>([
    ['first model on an idle camera', true, 'fall_detection', [], undefined,
      { kind: 'add', entry: { model_id: 'fall_detection' } }],
    ['second model', true, 'ppe_detection', ['fall_detection'], undefined,
      { kind: 'add', entry: { model_id: 'ppe_detection' } }],
    ['model with its setup config', true, 'geo_fencing', ['fall_detection'], zones,
      { kind: 'add', entry: { model_id: 'geo_fencing', config: zones } }],
    ['config edit on a running model', true, 'geo_fencing', ['geo_fencing'], zones,
      { kind: 'update', changes: { config: zones } }],
    ['tick an already running model', true, 'fall_detection', ['fall_detection'], undefined, { kind: 'noop' }],
    ['untick one of several', false, 'fall_detection', ['fall_detection', 'ppe_detection'], undefined, { kind: 'remove' }],
    ['untick the last one', false, 'fall_detection', ['fall_detection'], undefined, { kind: 'remove' }],
    ['untick a model that is not running', false, 'ppe_detection', ['fall_detection'], undefined, { kind: 'noop' }],
  ])('%s', (_name, enable, modelId, running, config, expected) => {
    expect(planToggle(enable, modelId, running, config as never)).toEqual(expected);
  });

  function spies() {
    return {
      add: vi.fn(async () => undefined),
      update: vi.fn(async () => undefined),
      remove: vi.fn(async () => undefined),
    };
  }

  it('makes exactly one matching call per action', async () => {
    const add = spies();
    await executeToggle({ kind: 'add', entry: { model_id: 'ppe_detection' } }, add);
    expect(add.add).toHaveBeenCalledExactlyOnceWith({ model_id: 'ppe_detection' });
    expect(add.update).not.toHaveBeenCalled();
    expect(add.remove).not.toHaveBeenCalled();

    const update = spies();
    await executeToggle({ kind: 'update', changes: { config: zones } }, update);
    expect(update.update).toHaveBeenCalledExactlyOnceWith({ config: zones });
    expect(update.add).not.toHaveBeenCalled();

    const remove = spies();
    await executeToggle({ kind: 'remove' }, remove);
    expect(remove.remove).toHaveBeenCalledOnce();
    expect(remove.add).not.toHaveBeenCalled();

    const noop = spies();
    await executeToggle({ kind: 'noop' }, noop);
    expect([noop.add, noop.update, noop.remove].every((f) => f.mock.calls.length === 0)).toBe(true);
  });

  it('propagates a failed call so the picker can show it', async () => {
    const failing = { ...spies(), add: vi.fn(async () => Promise.reject(new Error('409'))) };
    await expect(executeToggle({ kind: 'add', entry: { model_id: 'x' } }, failing)).rejects.toThrow('409');
  });
});

describe('uploaded (model store) models in the picker', () => {
  const builtin = (id: string) => status(id);
  const store = (id: string, over: Partial<ModelStatusInfo> = {}) =>
    ({ ...status(id), source: 'store', display_name: id.replace('_', ' ').toUpperCase(), reports_ppe: true, ...over }) as ModelStatusInfo;

  it('use their display name; built-in rows are unchanged', () => {
    expect(toAIModel(store('hard_hat', { display_name: 'Hard Hat' }), false).name).toBe('Hard Hat');
    const { pending, ...row } = toAIModel(builtin('ppe_detection'), true);
    expect(pending).toBe(false);
    expect(row).toEqual({ id: 'ppe_detection', name: 'Ppe Detection', state: 'active', requiresGeofencing: false });
  });

  it('a model whose every rule needs a zone is shown but cannot be enabled', () => {
    const harness = store('harness', { all_rules_need_zone: true, zone_required_rules: ['missing_harness'] });
    const row = toAIModel(harness, false);
    expect(row.state).toBe('unavailable');
    expect(row.disabledReason).toContain('missing_harness');
    // if it somehow runs already, it can still be switched off
    expect(toAIModel(harness, true).state).toBe('active');
  });

  it('a store model with zone types gets zone setup, keyed on its rules not its id', () => {
    const geofence = store('geofence', {
      display_name: 'Geo-Fencing', all_rules_need_zone: true,
      zone_required_rules: ['intrusion', 'exit'], zone_types: ['restricted', 'allowed'],
    });
    const row = toAIModel(geofence, false);
    expect(row.state).toBe('inactive'); // enabling opens the zone editor first
    expect(row.requiresGeofencing).toBe(true);
    expect(row.zoneTypes).toEqual(['restricted', 'allowed']);
    expect(row.disabledReason).toBeUndefined();
    // models without zone rules are unchanged
    const hardHat = toAIModel(store('hard_hat', { display_name: 'Hard Hat' }), false);
    expect(hardHat.requiresGeofencing).toBe(false);
    expect(hardHat.zoneTypes).toBeUndefined();
  });

  it('warn when built-in PPE and uploaded PPE models run together', () => {
    const available = [builtin('ppe_detection'), builtin('fall_detection'),
      store('hard_hat', { display_name: 'Hard Hat' }), store('safety_vest', { display_name: 'Safety Vest' }),
      store('forklift', { display_name: 'Forklift', reports_ppe: false })];
    expect(ppeOverlapWarning(available, ['fall_detection', 'hard_hat'])).toBeNull();
    expect(ppeOverlapWarning(available, ['ppe_detection', 'fall_detection'])).toBeNull();
    expect(ppeOverlapWarning(available, ['ppe_detection', 'forklift'])).toBeNull();
    expect(ppeOverlapWarning(available, ['ppe_detection', 'hard_hat', 'safety_vest'])).toBe(
      'PPE Detection and Hard Hat, Safety Vest both report missing PPE: each missing item will raise two violations.'
    );
  });
});


describe('models that are not installed or not working', () => {
  // 2026-11-19: a tab opened before the deploy added the retired geo_fencing;
  // the picker had no row for it, so it could be neither seen nor removed.
  const installed = [
    { ...status('gloves_2'), display_name: 'Gloves 2', source: 'store' },
    { ...status('fall_pose'), display_name: 'Fall Detection', source: 'store' },
    { ...status('geofence'), display_name: 'Geo-Fencing', source: 'store' },
  ] as unknown as ModelStatusInfo[];
  const ZONE = { zones: [{ id: 'zone_1' }] };

  function withStatus(
    entries: Array<{ model_id: string; status?: 'running' | 'failing' | 'unavailable'; message?: string; replacement?: string }>,
    notStarted: Array<{ model_id: string; message: string }> = []
  ): CameraModelsResponse {
    const r = modelsResponse(entries.map((e) => ({ model_id: e.model_id, config: e.model_id.startsWith('geo') ? ZONE : null })));
    r.models = r.models.map((m, i) => ({
      ...m,
      status: entries[i].status ?? 'running',
      message: entries[i].message ?? null,
      replacement: entries[i].replacement ?? null,
    }));
    r.not_started = notStarted.map((e) => ({
      model_id: e.model_id, model_version: null, config: null, fps_override: null, target_fps: 2,
      status: 'unavailable', reason: 'model_retired', message: e.message,
    }));
    return r;
  }

  it('a running retired model gets an unavailable row with Remove', () => {
    const server = withStatus([
      { model_id: 'gloves_2' },
      { model_id: 'geo_fencing', status: 'unavailable', message: 'geo_fencing is retired; use geofence', replacement: 'geofence' },
    ]);
    const rows = pickerModels(installed, ['gloves_2', 'geo_fencing'], null, server);
    expect(rows.map((r) => r.id)).toEqual(['gloves_2', 'fall_pose', 'geofence', 'geo_fencing']);
    expect(rows.at(-1)).toEqual({
      id: 'geo_fencing', name: 'Geo Fencing', state: 'unavailable', removable: true, pending: false,
      disabledReason: 'geo_fencing is retired; use geofence',
    });
  });

  it('before the server says why, a running model nobody lists is still shown', () => {
    const rows = pickerModels(installed, ['gloves_2', 'geo_fencing']);
    expect(rows.find((r) => r.id === 'geo_fencing')).toMatchObject({
      state: 'unavailable', removable: true, disabledReason: 'geo_fencing is not available on this system',
    });
  });

  it('a saved model that was not started gets a row too, and Remove targets it', () => {
    const server = withStatus([{ model_id: 'gloves_2' }], [{ model_id: 'ppe_detection', message: 'ppe_detection is retired' }]);
    const rows = pickerModels(installed, ['gloves_2'], null, server);
    expect(rows.find((r) => r.id === 'ppe_detection')).toMatchObject({ state: 'unavailable', removable: true });
    const s = streaming({ ai_enabled: true, models: ['gloves_2'] });
    expect(savedModelIdsFor(s, server)).toEqual(['gloves_2', 'ppe_detection']);
    expect(planToggle(false, 'ppe_detection', savedModelIdsFor(s, server))).toEqual({ kind: 'remove' });
  });

  it('a failing model keeps its row, marked degraded, with the reason', () => {
    const server = withStatus([{ model_id: 'fall_pose', status: 'failing', message: 'No result for 2 min 0 s: timeout' }]);
    const row = pickerModels(installed, ['fall_pose'], null, server).find((r) => r.id === 'fall_pose');
    expect(row).toMatchObject({ state: 'degraded', problem: 'No result for 2 min 0 s: timeout' });
    expect(row?.removable).toBeUndefined();
  });

  it('rows are unchanged when every model runs', () => {
    const server = withStatus([{ model_id: 'gloves_2' }]);
    expect(pickerModels(installed, ['gloves_2'], null, server)).toEqual(pickerModels(installed, ['gloves_2']));
  });

  it('tile chips: one per failing or unavailable model, with the server message', () => {
    const server = withStatus(
      [
        { model_id: 'gloves_2' },
        { model_id: 'fall_pose', status: 'failing', message: 'No result for 1 min 5 s: timeout' },
        { model_id: 'geo_fencing', status: 'unavailable', message: 'geo_fencing is retired; use geofence' },
      ],
      [{ model_id: 'ppe_detection', message: 'ppe_detection is retired' }]
    );
    expect(modelProblemsFor(server, installed)).toEqual([
      { modelId: 'fall_pose', name: 'Fall Detection', status: 'failing', message: 'No result for 1 min 5 s: timeout' },
      { modelId: 'geo_fencing', name: 'Geo Fencing', status: 'unavailable', message: 'geo_fencing is retired; use geofence' },
      { modelId: 'ppe_detection', name: 'Ppe Detection', status: 'unavailable', message: 'ppe_detection is retired' },
    ]);
    expect(modelProblemsFor(withStatus([{ model_id: 'gloves_2' }]), installed)).toEqual([]);
    expect(modelProblemsFor(undefined, installed)).toEqual([]);
  });

  it('an older backend without status fields shows no chips', () => {
    expect(modelProblemsFor(modelsResponse([{ model_id: 'gloves_2' }]), installed)).toEqual([]);
  });
});
