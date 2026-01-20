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
 * Fetch devices list
 *
 * Returns all registered cameras/devices.
 */
export async function fetchDevices(): Promise<DevicesListResponse> {
  const response = await apiGet<unknown>(DEVICES_PATH);
  return assertResponse(response, isDevicesListResponse, 'DevicesListResponse');
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
// Camera Status Helpers (F6 §4.4)
// ============================================================================

/**
 * Camera status (F6 §4.4)
 *
 * | is_active | streaming.active | Display     |
 * |-----------|------------------|-------------|
 * | true      | true             | "Live"      |
 * | true      | false            | "Offline"   |
 * | false     | any              | "Disabled"  |
 */
export type CameraStatus = 'live' | 'offline' | 'disabled';

/**
 * Derive camera status from device
 */
export function getCameraStatus(device: Device): CameraStatus {
  if (!device.is_active) {
    return 'disabled';
  }
  if (device.streaming.active) {
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
