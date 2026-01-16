import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys, type ViolationFilters } from '../queryKeys';
import { POLLING_INTERVALS } from '../pollingIntervals';
import {
  fetchViolations,
  fetchViolation,
  updateViolationStatus,
  getConfidenceCategory as apiGetConfidenceCategory,
  getConfidenceLabel,
} from '../api';
import type {
  ViolationsListResponse,
  Violation,
  ConfidenceCategory,
  UpdateViolationRequest,
} from '../api';

/**
 * Violations List Query Hook
 *
 * Fetches violations with 10s polling (F6 §11.1).
 *
 * Uses the centralized API client - no direct fetch calls.
 *
 * F6 §7.1: MUST NOT assume violations are returned in timestamp order.
 * Always use sort_by parameter.
 */
export function useViolationsQuery(filters?: ViolationFilters) {
  return useQuery({
    queryKey: queryKeys.violations.list(filters),
    queryFn: () => fetchViolations(filters),
    refetchInterval: POLLING_INTERVALS.VIOLATIONS,
    refetchIntervalInBackground: false,
  });
}

/**
 * Single Violation Detail Query Hook
 *
 * Fetches on-demand only (F6 §11.1: no polling for detail).
 *
 * Uses the centralized API client - no direct fetch calls.
 */
export function useViolationQuery(id: string) {
  return useQuery({
    queryKey: queryKeys.violations.detail(id),
    queryFn: () => fetchViolation(id),
    enabled: !!id,
    // No refetchInterval - on-demand only
  });
}

/**
 * Convert numeric confidence to categorical (F6 §3.2)
 *
 * HARD RULE: Frontend MUST NOT display numeric confidence.
 * Always use categorical labels.
 *
 * Re-exported from API module for convenience.
 */
export function getConfidenceCategory(confidence: number): ConfidenceCategory {
  return apiGetConfidenceCategory(confidence);
}

/**
 * Get display text for confidence category (F6 §3.2)
 *
 * Re-exported from API module for convenience.
 */
export function getConfidenceDisplay(confidence: number): string {
  return getConfidenceLabel(confidence);
}

// ============================================================================
// Violation Mutation Hooks (E5)
// ============================================================================

/**
 * Update Violation Status Mutation Hook
 *
 * Used for:
 * - Acknowledge (status: 'reviewed')
 * - Dismiss (status: 'dismissed')
 *
 * F6 §10.1: Uses optimistic update with rollback on failure.
 * F6 §11.2: Refetches list after action.
 *
 * HARD RULES:
 * - Action MUST rollback on failure
 * - Error MUST be shown inline or via toast
 * - No silent failures
 */
export function useUpdateViolationMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, update }: { id: string; update: UpdateViolationRequest }) =>
      updateViolationStatus(id, update),

    // F6 §10.1: Optimistic update
    onMutate: async ({ id, update }) => {
      // Cancel outgoing refetches to avoid overwriting optimistic update
      await queryClient.cancelQueries({ queryKey: queryKeys.violations.all });

      // Snapshot previous value for rollback
      const previousData = queryClient.getQueryData<ViolationsListResponse>(
        queryKeys.violations.list({ status: 'open' })
      );

      // Optimistically update the cache
      if (previousData && update.status) {
        queryClient.setQueryData<ViolationsListResponse>(
          queryKeys.violations.list({ status: 'open' }),
          (old) => {
            if (!old) return old;

            // If status is 'dismissed' or 'resolved', remove from open list
            if (update.status === 'dismissed' || update.status === 'resolved') {
              return {
                ...old,
                items: old.items.filter((v) => v.id !== id),
                total: old.total - 1,
              };
            }

            // Otherwise update the status in place
            return {
              ...old,
              items: old.items.map((v) =>
                v.id === id ? { ...v, status: update.status as Violation['status'] } : v
              ),
            };
          }
        );
      }

      return { previousData };
    },

    // Rollback on error
    onError: (_err, _variables, context) => {
      if (context?.previousData) {
        queryClient.setQueryData(
          queryKeys.violations.list({ status: 'open' }),
          context.previousData
        );
      }
    },

    // F6 §11.2: Refetch after mutation settles
    onSettled: () => {
      // Invalidate to ensure fresh data
      queryClient.invalidateQueries({ queryKey: queryKeys.violations.all });
    },
  });
}

/**
 * Acknowledge violation (convenience hook)
 *
 * Per F3 Flow 3: Marks as 'reviewed' with immediate feedback.
 */
export function useAcknowledgeViolation() {
  const mutation = useUpdateViolationMutation();

  return {
    ...mutation,
    acknowledge: (id: string) =>
      mutation.mutateAsync({ id, update: { status: 'reviewed' } }),
  };
}

/**
 * Dismiss violation (convenience hook)
 *
 * Per F3 Flow 3: Marks as 'dismissed' (false positive).
 * REQUIRES confirmation dialog before calling.
 */
export function useDismissViolation() {
  const mutation = useUpdateViolationMutation();

  return {
    ...mutation,
    dismiss: (id: string, notes?: string) =>
      mutation.mutateAsync({
        id,
        update: { status: 'dismissed', resolution_notes: notes },
      }),
  };
}

// Re-export types for consumers
export type { ViolationsListResponse, Violation, ConfidenceCategory, UpdateViolationRequest };
