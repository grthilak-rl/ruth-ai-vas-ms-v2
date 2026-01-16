import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../queryKeys';
import { POLLING_INTERVALS } from '../pollingIntervals';
import {
  fetchModelsStatus,
  getModelDisplay as apiGetModelDisplay,
  humanizeModelId as apiHumanizeModelId,
  isAnyModelHealthy as apiIsAnyModelHealthy,
  areAllModelsUnavailable as apiAreAllModelsUnavailable,
} from '../api';
import type { ModelsStatusResponse, ModelStatusInfo, ModelDisplayInfo } from '../api';

/**
 * Models Status Query Hook
 *
 * Fetches model status with 30s polling (F6 §11.1).
 *
 * Uses the centralized API client - no direct fetch calls.
 */
export function useModelsStatusQuery() {
  return useQuery({
    queryKey: queryKeys.models.status,
    queryFn: fetchModelsStatus,
    refetchInterval: POLLING_INTERVALS.MODELS_STATUS,
    refetchIntervalInBackground: false,
  });
}

/**
 * Get display strings for model status (F6 §4.3)
 *
 * Re-exported from API module for convenience.
 */
export function getModelDisplay(model: ModelStatusInfo): ModelDisplayInfo {
  return apiGetModelDisplay(model);
}

/**
 * Humanize model ID for display (F6 §12.3)
 *
 * HARD RULE: Frontend MUST NOT display raw model_id to Operators.
 *
 * Re-exported from API module for convenience.
 */
export function humanizeModelId(modelId: string, isAdmin: boolean = false): string {
  return apiHumanizeModelId(modelId, isAdmin);
}

/**
 * Check if any model is healthy
 *
 * Re-exported from API module for convenience.
 */
export function isAnyModelHealthy(models: ModelStatusInfo[]): boolean {
  return apiIsAnyModelHealthy(models);
}

/**
 * Check if all models are unavailable
 *
 * Re-exported from API module for convenience.
 */
export function areAllModelsUnavailable(models: ModelStatusInfo[]): boolean {
  return apiAreAllModelsUnavailable(models);
}

// Re-export types for consumers
export type { ModelsStatusResponse, ModelStatusInfo, ModelDisplayInfo };
