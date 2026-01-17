/**
 * Hardware API Types
 *
 * Types for the hardware monitoring endpoint.
 * Source: GET /api/v1/system/hardware
 *
 * Per F6 §9.1: Nullable fields MUST be typed as nullable.
 * Per F6 §7: NO assumptions about data presence.
 */

import type { ISOTimestamp } from './types';

/**
 * GPU hardware metrics
 */
export interface GPUMetrics {
  /** Whether a GPU is available */
  available: boolean;

  /** GPU model name (e.g., "NVIDIA RTX 3090") - null if no GPU */
  name: string | null;

  /** Total VRAM in GB - null if no GPU */
  vram_total_gb: number | null;

  /** Used VRAM in GB - null if no GPU */
  vram_used_gb: number | null;

  /** VRAM usage percentage (0-100) - null if no GPU */
  vram_percent: number | null;

  /** GPU compute utilization percentage (0-100) - null if no GPU */
  utilization_percent: number | null;

  /** GPU temperature in Celsius - null if unavailable */
  temperature_c: number | null;
}

/**
 * CPU hardware metrics
 */
export interface CPUMetrics {
  /** CPU model name (e.g., "Intel i7-12700K") - may be null */
  model: string | null;

  /** Number of CPU cores - may be null */
  cores: number | null;

  /** Current CPU usage percentage (0-100) */
  usage_percent: number;
}

/**
 * RAM memory metrics
 */
export interface RAMMetrics {
  /** Total RAM in GB */
  total_gb: number;

  /** Used RAM in GB */
  used_gb: number;

  /** RAM usage percentage (0-100) */
  percent: number;
}

/**
 * Individual AI model service status
 */
export interface ModelServiceStatus {
  /** Service name (e.g., "fall-detection", "ppe-detection") */
  name: string;

  /** Number of models loaded by this service */
  models: number;

  /** Service health status */
  status: 'healthy' | 'unhealthy' | 'unknown';
}

/**
 * Aggregated AI models metrics
 */
export interface ModelsMetrics {
  /** Total number of loaded models across all services */
  loaded_count: number;

  /** Individual service statuses */
  services: ModelServiceStatus[];
}

/**
 * System capacity estimates
 */
export interface CapacityMetrics {
  /** Number of cameras currently active */
  current_cameras: number;

  /** Estimated maximum cameras based on available resources */
  estimated_max_cameras: number;

  /** Available capacity headroom percentage (0-100) */
  headroom_percent: number;
}

/**
 * Hardware monitoring response
 *
 * Source: GET /api/v1/system/hardware
 *
 * This endpoint never fails - it always returns partial data if full metrics
 * are unavailable. For example:
 * - No GPU: gpu.available=false with null metrics
 * - Model service unreachable: status="unknown" with models=0
 */
export interface HardwareResponse {
  /** Timestamp of metrics collection */
  timestamp: ISOTimestamp;

  /** GPU metrics */
  gpu: GPUMetrics;

  /** CPU metrics */
  cpu: CPUMetrics;

  /** RAM metrics */
  ram: RAMMetrics;

  /** Loaded AI models metrics */
  models: ModelsMetrics;

  /** System capacity estimates */
  capacity: CapacityMetrics;
}
