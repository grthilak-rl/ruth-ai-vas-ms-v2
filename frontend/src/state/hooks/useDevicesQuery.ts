import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '../queryKeys';
import { POLLING_INTERVALS } from '../pollingIntervals';
import {
  fetchDevices,
  fetchDevice,
  getCameraStatus as apiGetCameraStatus,
  getCameraStatusLabel,
  getDetectionStatus as apiGetDetectionStatus,
  getDetectionStatusLabel,
  normalizeStreamState as apiNormalizeStreamState,
} from '../api';
import {
  startInference,
  stopInference,
  updateModelConfig,
  updateDeviceNaming,
  fetchManways,
  deriveDisplayName,
  type StartInferenceRequest,
  type DeviceNamingUpdate,
} from '../api/devices.api';
import type { ModelConfig } from '../../types/geofencing';
import type {
  DevicesListResponse,
  Device,
  CameraStatus,
  DetectionStatus,
} from '../api';

/**
 * Devices List Query Hook
 *
 * Fetches devices/cameras with 60s polling (F6 §11.1).
 *
 * Uses the centralized API client - no direct fetch calls.
 */
export function useDevicesQuery() {
  return useQuery({
    queryKey: queryKeys.devices.list(),
    queryFn: fetchDevices,
    refetchInterval: POLLING_INTERVALS.DEVICES,
    // Reuse cached response within half-interval so quick page hops
    // don't re-fire the (expensive) /api/v1/devices fanout.
    staleTime: POLLING_INTERVALS.DEVICES / 2,
    refetchIntervalInBackground: false,
  });
}

/**
 * Single Device Detail Query Hook
 *
 * Fetches on-demand only (no polling).
 *
 * Uses the centralized API client - no direct fetch calls.
 */
export function useDeviceQuery(id: string) {
  return useQuery({
    queryKey: queryKeys.devices.detail(id),
    queryFn: () => fetchDevice(id),
    enabled: !!id,
  });
}

// ============================================================================
// Inference mutation hooks — invalidate the devices query on success so the
// camera grid reflects the new streaming/ai state without waiting for the
// (now 120s) poll.
// ============================================================================

export function useStartInferenceMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ deviceId, request }: { deviceId: string; request: StartInferenceRequest }) =>
      startInference(deviceId, request),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.devices.all });
    },
  });
}

export function useStopInferenceMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ deviceId }: { deviceId: string }) => stopInference(deviceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.devices.all });
    },
  });
}

export function useUpdateModelConfigMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ deviceId, config }: { deviceId: string; config: ModelConfig }) =>
      updateModelConfig(deviceId, config),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.devices.all });
    },
  });
}

/**
 * Camera status derivation (F6 §4.4)
 *
 * Re-exported from API module for convenience.
 */
export function getCameraStatus(device: Device): CameraStatus {
  return apiGetCameraStatus(device);
}

export function getCameraStatusDisplay(status: CameraStatus): string {
  return getCameraStatusLabel(status);
}

/**
 * Detection status derivation (F6 §4.4)
 *
 * Re-exported from API module for convenience.
 */
export function getDetectionStatus(
  device: Device,
  modelHealthy: boolean = true
): DetectionStatus {
  return apiGetDetectionStatus(device, modelHealthy);
}

export function getDetectionStatusDisplay(status: DetectionStatus): string {
  return getDetectionStatusLabel(status);
}

/**
 * Normalize stream state (handles both uppercase and lowercase)
 *
 * Re-exported from API module for convenience.
 */
export function normalizeStreamState(
  state: string | null
): 'live' | 'stopped' | null {
  return apiNormalizeStreamState(state);
}

// Re-export types for consumers
export type { DevicesListResponse, Device, CameraStatus, DetectionStatus };

// ============================================================================
// Structured naming (phase 2)
// ============================================================================

/**
 * Manway vocabulary for autocomplete.
 *
 * Long staleTime: the set of manways changes only when someone names a
 * camera, and the mutation below invalidates it on success.
 */
export function useManwaysQuery() {
  return useQuery({
    queryKey: queryKeys.devices.manways(),
    queryFn: fetchManways,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Update a device's manway / in_out, writing through to VAS.
 *
 * Optimistic: the grid shows the new name immediately using the same
 * derivation rule VAS applies, so the operator never waits on the round
 * trip. On failure the previous cache snapshot is restored wholesale, so
 * Ruth cannot be left displaying a name VAS does not have.
 *
 * onSettled re-fetches regardless of outcome, replacing the optimistic guess
 * with what VAS actually stored (it normalizes manway to uppercase).
 */
export function useUpdateDeviceNamingMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ deviceId, update }: { deviceId: string; update: DeviceNamingUpdate }) =>
      updateDeviceNaming(deviceId, update),

    onMutate: async ({ deviceId, update }) => {
      // Stop in-flight refetches from clobbering the optimistic value.
      await queryClient.cancelQueries({ queryKey: queryKeys.devices.list() });

      const previous = queryClient.getQueryData<DevicesListResponse>(
        queryKeys.devices.list()
      );

      queryClient.setQueryData<DevicesListResponse>(
        queryKeys.devices.list(),
        (old) => {
          if (!old) return old;
          return {
            ...old,
            items: old.items.map((d) => {
              if (d.id !== deviceId) return d;
              // Only fields present in the update change; the rest hold.
              const manway = 'manway' in update ? update.manway ?? null : d.manway ?? null;
              const inOut = 'in_out' in update ? update.in_out ?? null : d.in_out ?? null;
              return {
                ...d,
                manway,
                in_out: inOut as Device['in_out'],
                display_name: deriveDisplayName(d.name, manway, inOut),
              };
            }),
          };
        }
      );

      return { previous };
    },

    onError: (_err, _vars, context) => {
      // Revert to the exact pre-edit snapshot.
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.devices.list(), context.previous);
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.devices.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.devices.manways() });
    },
  });
}
