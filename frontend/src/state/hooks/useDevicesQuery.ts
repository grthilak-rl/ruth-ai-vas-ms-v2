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
  type StartInferenceRequest,
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
