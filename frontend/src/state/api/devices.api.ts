/**
 * Devices API
 *
 * Device/camera management API (F6 §4.4).
 *
 * Source Endpoints:
 * - GET  /api/v1/devices
 * - GET  /api/v1/devices/{id}
 * - POST /api/v1/devices/{id}/start-inference
 * - POST /api/v1/devices/{id}/stop-inference
 * - POST /internal/sync/devices
 *
 * HARD RULES:
 * - F6 §8.1: MUST NOT infer camera online status from recent violations
 * - Use explicit streaming.active field
 * - Handle stream state in both uppercase and lowercase
 */

import { apiGet, apiPost, apiPatch } from './client';
import type { Device, DevicesListResponse, StreamState } from './types';
import { isDevice, isDevicesListResponse, assertResponse } from './validators';
import type { ModelConfig } from '../../types/geofencing';

/** API path for devices */
const DEVICES_PATH = '/api/v1/devices';

/**
 * API path for the VAS device-sync trigger.
 *
 * Ruth's device table is a cache of VAS's; it is only written by the
 * startup sync and by this endpoint. Served on the same origin — the
 * Ruth frontend nginx proxies /internal/ to the backend.
 */
const DEVICE_SYNC_PATH = '/internal/sync/devices';

/**
 * Fetch devices list
 *
 * Returns all registered cameras/devices.
 */
export async function fetchDevices(): Promise<DevicesListResponse> {
  const response = await apiGet<unknown>(DEVICES_PATH);
  return assertResponse(response, isDevicesListResponse, 'DevicesListResponse');
}

/**
 * Response from the device-sync trigger
 */
export interface DeviceSyncResponse {
  /** Human-readable summary, e.g. "Synced 8 devices from VAS" */
  message: string;
  /** How many VAS devices were upserted into Ruth's table */
  devices_synced: number;
}

/**
 * Trigger a device sync from VAS into Ruth's local devices table.
 *
 * POST /internal/sync/devices
 *
 * Callers should treat failure as non-fatal: the last-known device list
 * stays on screen. Retries are skipped deliberately — a failure here means
 * VAS is unreachable, and the client's default 502 policy would keep a
 * refresh spinner up for ~45s before giving the same answer.
 */
export async function syncDevicesFromVas(): Promise<DeviceSyncResponse> {
  return apiPost<DeviceSyncResponse>(
    DEVICE_SYNC_PATH,
    {},
    { skipRetry: true, timeout: 15_000 }
  );
}

/**
 * Fetch single device detail
 */
export async function fetchDevice(id: string): Promise<Device> {
  const response = await apiGet<unknown>(`${DEVICES_PATH}/${id}`);
  return assertResponse(response, isDevice, 'Device');
}

// ============================================================================
// Inference Control
// ============================================================================

/**
 * Request payload for starting inference
 */
export interface StartInferenceRequest {
  /** Model identifier */
  model_id: string;
  /** Optional model version */
  model_version?: string;
  /** Inference FPS (frames per second) */
  inference_fps?: number;
  /** Confidence threshold (0.0 - 1.0) */
  confidence_threshold?: number;
  /** Model-specific configuration (e.g., ROI, tank corners, alert thresholds) */
  model_config?: ModelConfig;
}

/**
 * Response from starting inference
 */
export interface StartInferenceResponse {
  /** Stream session ID */
  session_id: string;
  /** Device ID */
  device_id: string;
  /** Model ID */
  model_id: string;
  /** Session state */
  state: string;
  /** When the session started */
  started_at: string;
}

/**
 * Start AI inference for a device
 *
 * POST /api/v1/devices/{id}/start-inference
 */
export async function startInference(
  deviceId: string,
  request: StartInferenceRequest
): Promise<StartInferenceResponse> {
  return apiPost<StartInferenceResponse>(
    `${DEVICES_PATH}/${deviceId}/start-inference`,
    request
  );
}

/**
 * Stop AI inference for a device
 *
 * POST /api/v1/devices/{id}/stop-inference
 */
export async function stopInference(deviceId: string): Promise<void> {
  await apiPost<void>(`${DEVICES_PATH}/${deviceId}/stop-inference`, {});
}

/**
 * Response from updating model config
 */
export interface UpdateModelConfigResponse {
  /** Stream session ID */
  session_id: string;
  /** Device ID */
  device_id: string;
  /** Model ID */
  model_id: string;
  /** Whether config was updated */
  config_updated: boolean;
}

/**
 * Update model config for an active inference session
 *
 * PATCH /api/v1/devices/{id}/model-config
 */
export async function updateModelConfig(
  deviceId: string,
  config: ModelConfig
): Promise<UpdateModelConfigResponse> {
  return apiPatch<UpdateModelConfigResponse>(
    `${DEVICES_PATH}/${deviceId}/model-config`,
    { model_config: config }
  );
}

// ============================================================================
// Structured naming (phase 2) — edits write through to VAS
// ============================================================================

/** Fields an operator can change. Omit a key to leave it untouched in VAS. */
export interface DeviceNamingUpdate {
  /** Grouping key, e.g. "TANK5". null clears it. VAS uppercases it. */
  manway?: string | null;
  /** null clears it. */
  in_out?: 'IN' | 'OUT' | null;
}

/** What VAS actually stored, echoed back through Ruth's proxy. */
export interface DeviceNamingResponse {
  device_id: string;
  name: string;
  manway: string | null;
  in_out: string | null;
  display_name: string;
}

/**
 * Update a device's manway / in_out.
 *
 * Ruth's backend forwards this to VAS, which owns the fields and derives
 * display_name. The response carries what VAS stored — render that rather
 * than the values that were sent, since VAS normalizes them.
 */
export async function updateDeviceNaming(
  deviceId: string,
  update: DeviceNamingUpdate
): Promise<DeviceNamingResponse> {
  return apiPatch<DeviceNamingResponse>(
    `${DEVICES_PATH}/${deviceId}/naming`,
    update
  );
}

/**
 * Fetch the manway values already in use, for autocomplete.
 *
 * Returns [] on failure — a missing vocabulary must never block naming.
 */
export async function fetchManways(): Promise<string[]> {
  try {
    const res = await apiGet<{ manways: string[] }>(`${DEVICES_PATH}/manways`);
    return res?.manways ?? [];
  } catch {
    return [];
  }
}

/**
 * Derive the display name exactly as VAS does, for live preview while editing.
 *
 * Mirrors Device.display_name in the VAS backend: the segments that are set,
 * joined with "_", with the stable identifier always last. Preview only — the
 * saved value always comes back from VAS.
 */
export function deriveDisplayName(
  identifier: string,
  manway?: string | null,
  inOut?: string | null
): string {
  const segments = [manway?.trim().toUpperCase(), inOut].filter(Boolean);
  return [...segments, identifier].join('_');
}

// ============================================================================
// Camera Status Helpers (F6 §4.4)
// ============================================================================

/**
 * Camera status (F6 §4.4)
 *
 * Uses video_live field (VAS video stream status) for Online/Offline display.
 *
 * | is_active | streaming.video_live | Display     |
 * |-----------|----------------------|-------------|
 * | true      | true                 | "Live"      |
 * | true      | false                | "Offline"   |
 * | false     | any                  | "Disabled"  |
 */
export type CameraStatus = 'live' | 'offline' | 'disabled';

/**
 * Derive camera status from device
 *
 * Uses video_live (VAS video stream status), not active (AI inference status).
 */
export function getCameraStatus(device: Device): CameraStatus {
  if (!device.is_active) {
    return 'disabled';
  }
  // Use video_live for camera online/offline status
  if (device.streaming.video_live) {
    return 'live';
  }
  return 'offline';
}

/**
 * Get display label for camera status
 */
export function getCameraStatusLabel(status: CameraStatus): string {
  switch (status) {
    case 'live':
      return 'Live';
    case 'offline':
      return 'Offline';
    case 'disabled':
      return 'Disabled';
  }
}

// ============================================================================
// Detection Status Helpers (F6 §4.4)
// ============================================================================

/**
 * Detection status (F6 §4.4)
 *
 * | ai_enabled | Model Health         | Display              |
 * |------------|---------------------|----------------------|
 * | true       | healthy             | "Detection Active"   |
 * | true       | degraded/unhealthy  | "Detection Paused"   |
 * | false      | any                 | "Detection Disabled" |
 */
export type DetectionStatus = 'active' | 'paused' | 'disabled';

/**
 * Derive detection status from device
 *
 * @param device - The device to check
 * @param modelHealthy - Whether the model is healthy (from /models/status)
 */
export function getDetectionStatus(
  device: Device,
  modelHealthy: boolean = true
): DetectionStatus {
  if (!device.streaming.ai_enabled) {
    return 'disabled';
  }
  if (!modelHealthy) {
    return 'paused';
  }
  return 'active';
}

/**
 * Get display label for detection status
 */
export function getDetectionStatusLabel(status: DetectionStatus): string {
  switch (status) {
    case 'active':
      return 'Detection Active';
    case 'paused':
      return 'Detection Paused';
    case 'disabled':
      return 'Detection Disabled';
  }
}

// ============================================================================
// Stream State Helpers
// ============================================================================

/**
 * Normalize stream state (handles both uppercase and lowercase)
 *
 * Per CLAUDE.md: Handle stream states in both uppercase (LIVE, STOPPED)
 * and lowercase (live, stopped)
 */
export function normalizeStreamState(
  state: StreamState | null
): 'live' | 'stopped' | null {
  if (!state) return null;

  const lower = state.toLowerCase();
  if (lower === 'live') return 'live';
  if (lower === 'stopped') return 'stopped';

  return null;
}

/**
 * Check if stream is currently live
 */
export function isStreamLive(device: Device): boolean {
  const normalizedState = normalizeStreamState(device.streaming.state);
  return device.streaming.active && normalizedState === 'live';
}

// ============================================================================
// Re-exports for consumers
// ============================================================================

export type { Device, DevicesListResponse, DeviceStreaming, StreamState } from './types';
