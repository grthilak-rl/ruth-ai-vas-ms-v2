import { useQuery } from '@tanstack/react-query';
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
