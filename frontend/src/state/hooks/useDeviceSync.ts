import { useCallback, useSyncExternalStore } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '../queryKeys';
import { syncDevicesFromVas } from '../api/devices.api';

/**
 * Device Sync Hook
 *
 * Ruth's devices table is a cache of VAS's. Before this hook it was only
 * written at backend startup, so a camera added in the VAS admin portal
 * stayed invisible in Ruth until ruth-ai-backend was restarted.
 *
 * This drives POST /internal/sync/devices on user action — dashboard mount
 * and Camera Selector open — then invalidates the devices query so the
 * dropdown updates in place.
 *
 * Deliberately NOT a timer. Cameras change occasionally; a constant poll
 * would put load on VAS for nothing.
 *
 * The throttle/in-flight state lives at module scope rather than in
 * component state because several components (the dashboard and every
 * CameraSelectorDropdown instance it renders) request syncs independently.
 * Sharing it means mount + immediate open is one request, not two, and a
 * spinner started by one caller is visible to all of them.
 */

/** Minimum gap between non-forced syncs. Repeated opens inside this window are no-ops. */
export const DEVICE_SYNC_THROTTLE_MS = 15_000;

/** Outcome of a sync request. */
export type DeviceSyncOutcome =
  /** VAS was contacted and Ruth's device table was refreshed */
  | 'synced'
  /** Skipped — a sync completed within DEVICE_SYNC_THROTTLE_MS */
  | 'throttled'
  /** VAS unreachable or the backend rejected the sync; last-known list stands */
  | 'failed';

interface DeviceSyncState {
  /** A sync is in flight right now */
  isSyncing: boolean;
  /** Timestamp of the last completed attempt (success or failure), or null */
  lastAttemptAt: number | null;
  /** The last completed attempt failed */
  lastSyncFailed: boolean;
}

const INITIAL_STATE: DeviceSyncState = {
  isSyncing: false,
  lastAttemptAt: null,
  lastSyncFailed: false,
};

let state: DeviceSyncState = INITIAL_STATE;
let inFlight: Promise<DeviceSyncOutcome> | null = null;
const listeners = new Set<() => void>();

function setState(patch: Partial<DeviceSyncState>): void {
  state = { ...state, ...patch };
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): DeviceSyncState {
  return state;
}

async function runSync(): Promise<DeviceSyncOutcome> {
  setState({ isSyncing: true });
  try {
    await syncDevicesFromVas();
    setState({ isSyncing: false, lastAttemptAt: Date.now(), lastSyncFailed: false });
    return 'synced';
  } catch {
    // Non-fatal by contract: callers keep rendering the last-known device
    // list and surface a subtle "couldn't refresh" hint. lastAttemptAt is
    // stamped on failure too, so an unreachable VAS is not re-hit on every
    // dropdown open.
    setState({ isSyncing: false, lastAttemptAt: Date.now(), lastSyncFailed: true });
    return 'failed';
  } finally {
    inFlight = null;
  }
}

/**
 * Request a device sync, deduplicated and throttled across all callers.
 *
 * @param force - Bypass the throttle (the manual "Refresh" button). Still
 *                joins an in-flight sync rather than starting a second one.
 */
export function requestDeviceSync(force = false): Promise<DeviceSyncOutcome> {
  if (inFlight) {
    return inFlight;
  }

  const sinceLast =
    state.lastAttemptAt === null ? Infinity : Date.now() - state.lastAttemptAt;

  if (!force && sinceLast < DEVICE_SYNC_THROTTLE_MS) {
    return Promise.resolve('throttled');
  }

  inFlight = runSync();
  return inFlight;
}

/** Reset module state. Test-only. */
export function resetDeviceSyncState(): void {
  state = INITIAL_STATE;
  inFlight = null;
}

export interface UseDeviceSyncResult {
  /**
   * Kick off a sync. Resolves once the device list has been invalidated.
   * Never rejects — inspect the outcome instead.
   */
  syncNow: (force?: boolean) => Promise<DeviceSyncOutcome>;
  /** A sync is in flight (shared across all callers) */
  isSyncing: boolean;
  /** The last completed attempt failed */
  lastSyncFailed: boolean;
}

export function useDeviceSync(): UseDeviceSyncResult {
  const queryClient = useQueryClient();
  const { isSyncing, lastSyncFailed } = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getSnapshot
  );

  const syncNow = useCallback(
    async (force = false): Promise<DeviceSyncOutcome> => {
      const outcome = await requestDeviceSync(force);

      // Only refetch when the table actually changed. A throttled or failed
      // sync leaves the cache as-is, so re-fetching would be pure noise.
      if (outcome === 'synced') {
        await queryClient.invalidateQueries({ queryKey: queryKeys.devices.all });
      }

      return outcome;
    },
    [queryClient]
  );

  return { syncNow, isSyncing, lastSyncFailed };
}
