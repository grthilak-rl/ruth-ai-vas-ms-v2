/**
 * Models API
 *
 * READ-ONLY API for AI model status (F6 §4.3).
 *
 * Source Endpoint: GET /api/v1/models/status
 *
 * HARD RULES:
 * - F6 §8.1: MUST NOT infer model health from detection frequency
 * - F6 §4.3: Operators MUST NOT see model_id as raw string
 * - Display as "Detection" or "AI Detection" for operators
 */

import { apiGet } from './client';
import type { ModelsStatusResponse, ModelStatusInfo } from './types';
import { isModelsStatusResponse, assertResponse } from './validators';

/** API path for models status */
const MODELS_STATUS_PATH = '/api/v1/models/status';

/**
 * Fetch models status
 *
 * Returns status and health of all AI models.
 */
export async function fetchModelsStatus(): Promise<ModelsStatusResponse> {
  const response = await apiGet<unknown>(MODELS_STATUS_PATH);
  return assertResponse(response, isModelsStatusResponse, 'ModelsStatusResponse');
}

// ============================================================================
// Model Display Helpers (F6 §4.3)
// ============================================================================

/**
 * Model display info for different personas
 */
export interface ModelDisplayInfo {
  /** What operators see (simplified) */
  operatorDisplay: string;
  /** What admins see (detailed) */
  adminDisplay: string;
}

/**
 * Get display strings for model status (F6 §4.3)
 *
 * | Backend Status | Backend Health | Operator Sees           | Admin Sees           |
 * |----------------|----------------|-------------------------|----------------------|
 * | active         | healthy        | "Detection Active"      | "Active / Healthy"   |
 * | active         | degraded       | "Detection Degraded"    | "Active / Degraded"  |
 * | active         | unhealthy      | "Detection Paused"      | "Active / Unhealthy" |
 * | idle           | any            | "Detection Paused"      | "Idle"               |
 * | starting       | any            | "Detection Starting..." | "Starting"           |
 * | stopping       | any            | "Detection Stopping..." | "Stopping"           |
 * | error          | any            | "Detection Paused"      | "Error"              |
 *
 * HARD RULE: Operators MUST NOT see model_id. Display as "Detection".
 */
export function getModelDisplay(model: ModelStatusInfo): ModelDisplayInfo {
  const { status, health } = model;

  // Operator display - simplified, no model details
  let operatorDisplay: string;
  switch (status) {
    case 'active':
      if (health === 'healthy') {
        operatorDisplay = 'Detection Active';
      } else if (health === 'degraded') {
        operatorDisplay = 'Detection Degraded';
      } else {
        operatorDisplay = 'Detection Paused';
      }
      break;
    case 'starting':
      operatorDisplay = 'Detection Starting...';
      break;
    case 'stopping':
      operatorDisplay = 'Detection Stopping...';
      break;
    case 'idle':
    case 'error':
    default:
      operatorDisplay = 'Detection Paused';
      break;
  }

  // Admin display - detailed
  let adminDisplay: string;
  switch (status) {
    case 'active':
      adminDisplay = `Active / ${capitalize(health)}`;
      break;
    case 'starting':
      adminDisplay = 'Starting';
      break;
    case 'stopping':
      adminDisplay = 'Stopping';
      break;
    case 'idle':
      adminDisplay = 'Idle';
      break;
    case 'error':
      adminDisplay = 'Error';
      break;
    default:
      adminDisplay = 'Unknown';
      break;
  }

  return { operatorDisplay, adminDisplay };
}

/**
 * Humanize model ID for display (F6 §12.3)
 *
 * | Source Value      | Operator Display | Admin Display      |
 * |-------------------|------------------|---------------------|
 * | fall_detection    | "Detection"      | "Fall Detection"    |
 * | any model_id      | "Detection"      | Humanized name      |
 *
 * HARD RULE: Frontend MUST NOT display raw model_id to Operators.
 */
export function humanizeModelId(modelId: string, isAdmin: boolean = false): string {
  if (!isAdmin) {
    // Operators see generic "Detection"
    return 'Detection';
  }

  // Admins see humanized model name
  return modelId
    .split('_')
    .map(capitalize)
    .join(' ');
}

function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

// ============================================================================
// Model Health Helpers
// ============================================================================

/**
 * Check if any model is healthy and active
 */
export function isAnyModelHealthy(models: ModelStatusInfo[]): boolean {
  return models.some(
    (m) => m.status === 'active' && m.health === 'healthy'
  );
}

/**
 * Check if all models are unavailable
 */
export function areAllModelsUnavailable(models: ModelStatusInfo[]): boolean {
  return models.every(
    (m) => m.status === 'error' || m.status === 'idle' || m.health === 'unhealthy'
  );
}

/**
 * Get overall model health summary
 */
export type OverallModelHealth = 'healthy' | 'degraded' | 'unavailable';

export function getOverallModelHealth(models: ModelStatusInfo[]): OverallModelHealth {
  if (models.length === 0) return 'unavailable';

  const hasHealthy = models.some(
    (m) => m.status === 'active' && m.health === 'healthy'
  );
  if (hasHealthy) return 'healthy';

  const hasDegraded = models.some(
    (m) => m.status === 'active' && m.health === 'degraded'
  );
  if (hasDegraded) return 'degraded';

  return 'unavailable';
}

// ============================================================================
// Re-exports for consumers
// ============================================================================

export type { ModelsStatusResponse, ModelStatusInfo, ModelStatus, ModelHealth } from './types';
