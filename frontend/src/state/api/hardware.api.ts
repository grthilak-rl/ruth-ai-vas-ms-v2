/**
 * Hardware API
 *
 * READ-ONLY API for hardware monitoring metrics.
 *
 * Source Endpoint: GET /api/v1/system/hardware
 *
 * Returns GPU, CPU, RAM, loaded AI models, and capacity estimates.
 */

import { apiGet } from './client';
import type { HardwareResponse } from './hardware.types';

/** API path for hardware endpoint */
const HARDWARE_PATH = '/api/v1/system/hardware';

/**
 * Fetch hardware metrics
 *
 * Returns real-time hardware utilization metrics including GPU, CPU, RAM,
 * loaded AI models, and capacity estimates.
 *
 * This endpoint never fails - it always returns partial data if full metrics
 * are unavailable (e.g., GPU unavailable returns gpu.available=false).
 */
export async function fetchHardware(): Promise<HardwareResponse> {
  return apiGet<HardwareResponse>(HARDWARE_PATH);
}

// ============================================================================
// Utility Functions
// ============================================================================

/**
 * Get usage level for percentage values
 *
 * | Usage      | Color  | Meaning                   |
 * |------------|--------|---------------------------|
 * | healthy    | green  | Under 70% utilization     |
 * | warning    | yellow | 70-85% utilization        |
 * | critical   | red    | Over 85% utilization      |
 */
export type UsageLevel = 'healthy' | 'warning' | 'critical';

export function getUsageLevel(percent: number | null | undefined): UsageLevel {
  if (percent == null) return 'healthy';
  if (percent >= 85) return 'critical';
  if (percent >= 70) return 'warning';
  return 'healthy';
}

/**
 * Format bytes as human-readable GB
 */
export function formatGB(gb: number | null | undefined): string {
  if (gb == null) return '—';
  return `${gb.toFixed(1)}GB`;
}

/**
 * Format percentage for display
 */
export function formatPercent(percent: number | null | undefined): string {
  if (percent == null) return '—';
  return `${Math.round(percent)}%`;
}

/**
 * Get time since last update in human-readable format
 */
export function getTimeSinceUpdate(timestamp: string | undefined): string {
  if (!timestamp) return 'Unknown';

  try {
    const lastUpdate = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - lastUpdate.getTime();
    const diffSeconds = Math.floor(diffMs / 1000);

    if (diffSeconds < 0) return 'just now';
    if (diffSeconds < 60) return `${diffSeconds}s ago`;
    if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)}m ago`;
    return `${Math.floor(diffSeconds / 3600)}h ago`;
  } catch {
    return 'Unknown';
  }
}

// ============================================================================
// Re-exports for consumers
// ============================================================================

export type {
  HardwareResponse,
  GPUMetrics,
  CPUMetrics,
  RAMMetrics,
  ModelServiceStatus,
  ModelsMetrics,
  CapacityMetrics,
} from './hardware.types';
