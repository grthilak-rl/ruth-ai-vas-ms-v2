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
 * Normalize health status from backend
 *
 * Backend may return 'healthy', 'degraded', or 'unhealthy'.
 * VAS backend returns only 'healthy' or 'unhealthy'.
 */
function normalizeHealthStatus(status: string): HealthResponse['status'] {
  if (status === 'healthy') return 'healthy';
  if (status === 'degraded') return 'degraded';
  return 'unhealthy';
}

/**
 * Health response with fallback for VAS backend format
 *
 * The VAS backend returns a simpler health format:
 * { status: "healthy", service: "VAS Backend", version: "1.0.0" }
 *
 * This function handles both Ruth AI extended format and VAS simple formats.
 */
export async function fetchHealthWithFallback(): Promise<HealthResponse> {
  const response = await apiGet<HealthResponse>(HEALTH_PATH);

  // Ensure minimum required fields and normalize status
  return {
    status: normalizeHealthStatus(response.status),
    service: response.service ?? 'Unknown',
    version: response.version ?? 'Unknown',
    timestamp: response.timestamp,
    components: response.components,
    uptime_seconds: response.uptime_seconds,
    error: response.error,
  };
}

// ============================================================================
// Utility Functions
// ============================================================================

/**
 * Format uptime in human-readable form
 *
 * Examples: "2d 5h 30m", "5h 30m", "30m", "45s"
 */
export function formatUptime(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return 'Unknown';

  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  const parts: string[] = [];
  if (days > 0) parts.push(`${days}d`);
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  if (parts.length === 0 && secs > 0) parts.push(`${secs}s`);

  return parts.length > 0 ? parts.join(' ') : '< 1s';
}

/**
 * Get human-readable time since last check
 *
 * @param timestamp - ISO timestamp of last check
 * @returns "5s ago", "2m ago", etc.
 */
export function getTimeSinceLastCheck(timestamp: string | undefined): string {
  if (!timestamp) return 'Unknown';

  try {
    const lastCheck = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - lastCheck.getTime();
    const diffSeconds = Math.floor(diffMs / 1000);

    if (diffSeconds < 0) return 'just now';
    if (diffSeconds < 60) return `${diffSeconds}s ago`;
    if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)}m ago`;
    return `${Math.floor(diffSeconds / 3600)}h ago`;
  } catch {
    return 'Unknown';
  }
}

/**
 * Get component display name for UI
 */
export function getComponentDisplayName(componentKey: string): string {
  const names: Record<string, string> = {
    database: 'Database',
    redis: 'Redis',
    ai_runtime: 'AI Runtime',
    vas: 'VAS',
    nlp_chat: 'NLP Chat',
  };
  return names[componentKey] ?? componentKey;
}

// ============================================================================
// Re-exports for consumers
// ============================================================================

export type {
  HealthResponse,
  HealthStatus,
  ComponentHealthStatus,
  HealthComponents,
  ComponentHealth,
  DatabaseHealthDetails,
  RedisHealthDetails,
  AIRuntimeHealthDetails,
  VASHealthDetails,
  NLPChatHealthDetails,
} from './types';
