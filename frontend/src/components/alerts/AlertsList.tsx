import { useState, useCallback, useMemo } from 'react';
import {
  useViolationsQuery,
  useAcknowledgeViolation,
  useDismissViolation,
} from '../../state';
import type { Violation, ViolationStatus } from '../../state/api';
import type { AlertFilters } from './AlertsFilterSidebar';
import { ViolationCard } from './ViolationCard';
import { DismissConfirmationDialog } from './DismissConfirmationDialog';
import { Toast, type ToastType } from './Toast';
import { AlertsListSkeleton } from './AlertsListSkeleton';
import './AlertsList.css';

/**
 * Sort violations explicitly (F6 §7.1)
 *
 * HARD RULE: MUST NOT assume backend order.
 * Frontend must sort explicitly.
 *
 * Sorting: newest first by timestamp.
 */
function sortViolations(violations: Violation[]): Violation[] {
  return [...violations].sort((a, b) => {
    const dateA = new Date(a.timestamp).getTime();
    const dateB = new Date(b.timestamp).getTime();
    return dateB - dateA; // Newest first
  });
}

/**
 * Convert AlertFilters to API query parameters
 */
function filtersToQueryParams(filters: AlertFilters) {
  // For status, we need to pick one or query multiple
  // Since the API only supports one status, we'll use the first selected
  // If multiple are selected, we fetch without status filter and filter client-side
  const selectedStatuses = filters.statuses;
  const singleStatus = selectedStatuses.length === 1 ? selectedStatuses[0] : undefined;

  // Convert dates to ISO strings with time
  let since: string | undefined;
  let until: string | undefined;

  if (filters.dateFrom) {
    // Start of day
    since = `${filters.dateFrom}T00:00:00Z`;
  }

  if (filters.dateTo) {
    // End of day
    until = `${filters.dateTo}T23:59:59Z`;
  }

  return {
    status: singleStatus,
    camera_id: filters.cameraId || undefined,
    since,
    until,
    sort_by: 'timestamp' as const,
    sort_order: 'desc' as const,
  };
}

/**
 * Filter violations by selected statuses (client-side)
 * Used when multiple statuses are selected
 */
function filterByStatuses(violations: Violation[], statuses: ViolationStatus[]): Violation[] {
  if (statuses.length === 0) return violations; // No filter = all
  return violations.filter(v => statuses.includes(v.status as ViolationStatus));
}

interface AlertsListProps {
  /** Filter configuration from sidebar */
  filters: AlertFilters;
}

/**
 * Alerts List Component (F4/F5-aligned)
 *
 * Main list view for active violations.
 *
 * Per F5 §A1:
 * - New items prepend without scroll jump (via CSS)
 * - Each action completes independently
 * - No blocking between cards
 *
 * Per F4:
 * - Loading: Skeleton placeholders
 * - Empty: "No active violations" message
 * - Error: Friendly message + retry
 *
 * HARD RULES:
 * - F6 §7.1: MUST NOT assume backend order - sort explicitly
 * - F5: One failing action MUST NOT block others
 * - F3 Flow 3: Dismiss requires confirmation
 */
export function AlertsList({ filters }: AlertsListProps) {
  // Convert filters to query parameters
  const queryParams = useMemo(() => filtersToQueryParams(filters), [filters]);

  // Fetch violations with filters
  const {
    data,
    isLoading,
    isError,
    refetch,
  } = useViolationsQuery(queryParams);

  // Action mutations
  const acknowledgeMutation = useAcknowledgeViolation();
  const dismissMutation = useDismissViolation();

  // Track per-card action state
  const [pendingActions, setPendingActions] = useState<Record<string, 'acknowledge' | 'dismiss'>>({});
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({});

  // Dismiss confirmation dialog state
  const [dismissDialogState, setDismissDialogState] = useState<{
    isOpen: boolean;
    violationId: string | null;
  }>({ isOpen: false, violationId: null });

  // Toast state
  const [toast, setToast] = useState<{
    message: string;
    type: ToastType;
    isVisible: boolean;
  }>({ message: '', type: 'success', isVisible: false });

  // Sort and filter violations
  const sortedViolations = useMemo(() => {
    if (!data?.items) return [];

    // If multiple statuses are selected, we fetched without status filter
    // so we need to filter client-side
    let violations = data.items;
    if (filters.statuses.length !== 1) {
      violations = filterByStatuses(violations, filters.statuses);
    }

    return sortViolations(violations);
  }, [data?.items, filters.statuses]);

  // Handle acknowledge action
  const handleAcknowledge = useCallback(async (id: string) => {
    // Clear any previous error for this card
    setActionErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });

    // Mark as pending
    setPendingActions((prev) => ({ ...prev, [id]: 'acknowledge' }));

    try {
      await acknowledgeMutation.acknowledge(id);

      // Show success toast
      setToast({
        message: 'Violation marked as reviewed',
        type: 'success',
        isVisible: true,
      });
    } catch (err) {
      // Show inline error (F5 §B3: no silent failures)
      const message = err instanceof Error ? err.message : 'Couldn\'t save. Please try again.';
      setActionErrors((prev) => ({ ...prev, [id]: message }));
    } finally {
      // Clear pending state
      setPendingActions((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    }
  }, [acknowledgeMutation]);

  // Handle dismiss button click (opens confirmation)
  const handleDismissClick = useCallback((id: string) => {
    setDismissDialogState({ isOpen: true, violationId: id });
  }, []);

  // Handle dismiss confirmation
  const handleDismissConfirm = useCallback(async () => {
    const id = dismissDialogState.violationId;
    if (!id) return;

    // Clear any previous error
    setActionErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });

    // Mark as pending
    setPendingActions((prev) => ({ ...prev, [id]: 'dismiss' }));

    try {
      await dismissMutation.dismiss(id);

      // Close dialog
      setDismissDialogState({ isOpen: false, violationId: null });

      // Show success toast (F5 §A1: "Toast: Violation dismissed")
      setToast({
        message: 'Violation dismissed',
        type: 'success',
        isVisible: true,
      });
    } catch (err) {
      // Close dialog and show inline error
      setDismissDialogState({ isOpen: false, violationId: null });
      const message = err instanceof Error ? err.message : 'Couldn\'t dismiss. Please try again.';
      setActionErrors((prev) => ({ ...prev, [id]: message }));
    } finally {
      // Clear pending state
      setPendingActions((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    }
  }, [dismissDialogState.violationId, dismissMutation]);

  // Handle dismiss cancel
  const handleDismissCancel = useCallback(() => {
    setDismissDialogState({ isOpen: false, violationId: null });
  }, []);

  // Handle toast dismiss
  const handleToastDismiss = useCallback(() => {
    setToast((prev) => ({ ...prev, isVisible: false }));
  }, []);

  // Loading state (F4: skeleton placeholders)
  if (isLoading) {
    return <AlertsListSkeleton />;
  }

  // Error state (F4: friendly message + retry)
  if (isError) {
    return (
      <div className="alerts-list__error" role="alert">
        <p className="alerts-list__error-message">
          Couldn't load alerts. Please try again.
        </p>
        <button
          type="button"
          className="alerts-list__error-retry"
          onClick={() => refetch()}
        >
          Retry
        </button>
      </div>
    );
  }

  // Empty state
  if (sortedViolations.length === 0) {
    // Customize message based on filters
    const hasFilters = filters.statuses.length > 0 ||
      filters.dateFrom !== null ||
      filters.dateTo !== null ||
      filters.cameraId !== null;

    return (
      <div className="alerts-list__empty">
        <p className="alerts-list__empty-message">
          {hasFilters ? 'No violations match your filters' : 'No active violations'}
        </p>
        <p className="alerts-list__empty-hint">
          {hasFilters
            ? 'Try adjusting your filter criteria.'
            : 'New detections will appear here automatically.'}
        </p>
      </div>
    );
  }

  // Normal state with violations
  return (
    <>
      <div className="alerts-list">
        {sortedViolations.map((violation) => (
          <ViolationCard
            key={violation.id}
            violation={violation}
            onAcknowledge={handleAcknowledge}
            onDismiss={handleDismissClick}
            isActionPending={!!pendingActions[violation.id]}
            pendingAction={pendingActions[violation.id] || null}
            actionError={actionErrors[violation.id] || null}
          />
        ))}
      </div>

      {/* Dismiss confirmation dialog */}
      <DismissConfirmationDialog
        isOpen={dismissDialogState.isOpen}
        onConfirm={handleDismissConfirm}
        onCancel={handleDismissCancel}
        isPending={
          dismissDialogState.violationId
            ? pendingActions[dismissDialogState.violationId] === 'dismiss'
            : false
        }
      />

      {/* Toast notifications */}
      <Toast
        message={toast.message}
        type={toast.type}
        isVisible={toast.isVisible}
        onDismiss={handleToastDismiss}
      />
    </>
  );
}
