/**
 * Health API
 *
 * READ-ONLY API for system health (F6 §4).
 *
 * Source Endpoint: GET /api/v1/health
 *
 * HARD RULES (F6 §8.1):
 * - MUST NOT infer health from API latency
 * - MUST NOT infer health from the absence of violations
 * - Source of truth is ONLY this endpoint
 */

import { apiGet } from './client';
import type { HealthResponse } from './types';
import { isHealthResponse, assertResponse } from './validators';

/** API path for health endpoint */
const HEALTH_PATH = '/api/v1/health';

/**
 * Fetch system health
 *
 * Returns the health status of the Ruth AI backend.
 *
 * F6 §4.2 Global Status Derivation:
 * - status = "healthy" → Display "All Systems OK" (green)
 * - status = "unhealthy" with any component unhealthy → Display "Degraded" (yellow)
 * - API call fails → Display "Offline" (red)
 */
export async function fetchHealth(): Promise<HealthResponse> {
  const response = await apiGet<unknown>(HEALTH_PATH);
  return assertResponse(response, isHealthResponse, 'HealthResponse');
}

/**
 * Health response with fallback for VAS backend format
 *
 * The VAS backend returns a simpler health format:
 * { status: "healthy", service: "VAS Backend", version: "1.0.0" }
 *
 * This function handles both Ruth AI and VAS formats.
 */
export async function fetchHealthWithFallback(): Promise<HealthResponse> {
  const response = await apiGet<HealthResponse>(HEALTH_PATH);

  // Ensure minimum required fields
  return {
    status: response.status === 'healthy' ? 'healthy' : 'unhealthy',
    service: response.service ?? 'Unknown',
    version: response.version ?? 'Unknown',
    timestamp: response.timestamp,
    components: response.components,
    error: response.error,
  };
}

// ============================================================================
// Re-exports for consumers
// ============================================================================

export type { HealthResponse, HealthStatus, HealthComponents, ComponentHealth } from './types';
