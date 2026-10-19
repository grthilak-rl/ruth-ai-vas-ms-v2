import { useState, useCallback, useMemo } from 'react';
import { useApplyViolationStatus, useIncidentsQuery } from '../../state';
import type { Incident, Violation } from '../../state/api';
import type { AlertFilters } from './AlertsFilterSidebar';
import { IncidentCard, type IncidentAction } from './IncidentCard';
import { DismissConfirmationDialog } from './DismissConfirmationDialog';
import { Toast, type ToastType } from './Toast';
import { AlertsListSkeleton } from './AlertsListSkeleton';
import { Pagination } from '../ui';
import { alertFiltersToParams } from './alertFilters';
import { cameraHeadline, formatIncidentSpan } from '../../utils/violationDisplay';
import './AlertsList.css';

/** Default page size (incidents) */
const DEFAULT_PAGE_SIZE = 10;

type PendingConfirm =
  | { kind: 'group'; incident: Incident; action: IncidentAction; ids: string[] }
  | { kind: 'member'; incident: Incident; violation: Violation };

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

interface AlertsListProps {
  /** Filter configuration from sidebar */
  filters: AlertFilters;
}

/**
 * Alerts List — violations grouped into incidents.
 *
 * Repeated violations (same camera + specific type, each within the
 * backend's window of the previous) are one card with a count and span, so
 * a camera firing every few seconds no longer buries everything else.
 *
 * Actions:
 * - On a card: apply to the incident's OPEN violations, after a count
 *   confirmation ("Dismiss 12 violations?"). The ids are fixed when the
 *   dialog opens, so repeats arriving meanwhile are not swept in unseen.
 * - On an expanded row: that violation alone (Dismiss still confirms).
 * Failures are reported per incident, with how many did not save.
 */
export function AlertsList({ filters }: AlertsListProps) {
  // The page belongs to the filters it was chosen under: change a filter
  // and the list is back on page 1, derived rather than reset in an effect.
  const filterKey = JSON.stringify(filters);
  const [paging, setPaging] = useState({ key: filterKey, page: 1 });
  const currentPage = paging.key === filterKey ? paging.page : 1;
  const setCurrentPage = useCallback((page: number) => setPaging({ key: filterKey, page }), [filterKey]);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  const queryParams = useMemo(
    () => alertFiltersToParams(filters, currentPage, pageSize),
    [filters, currentPage, pageSize]
  );
  const { data, isLoading, isFetching, isError, refetch } = useIncidentsQuery(queryParams);

  const handlePageChange = useCallback((page: number) => {
    setCurrentPage(page);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [setCurrentPage]);

  const handlePageSizeChange = useCallback((size: number) => {
    setPageSize(size);
    setCurrentPage(1);
  }, [setCurrentPage]);

  const applyStatus = useApplyViolationStatus();
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const [toast, setToast] = useState<{ message: string; type: ToastType; isVisible: boolean }>({
    message: '',
    type: 'success',
    isVisible: false,
  });

  /** Apply an action to ids; errors are recorded against `cardKey`. */
  const run = useCallback(
    async (cardKey: string, ids: string[], action: IncidentAction) => {
      setErrors((prev) => {
        const next = { ...prev };
        delete next[cardKey];
        return next;
      });
      setPending((prev) => ({ ...prev, [cardKey]: true }));
      const { succeeded, failed } = await applyStatus(ids, {
        status: action === 'review' ? 'reviewed' : 'dismissed',
      });
      setPending((prev) => {
        const next = { ...prev };
        delete next[cardKey];
        return next;
      });
      if (failed.length) {
        setErrors((prev) => ({
          ...prev,
          [cardKey]: `${failed.length} of ${ids.length} couldn't be saved. Please try again.`,
        }));
      }
      if (succeeded.length) {
        const verb = action === 'review' ? 'marked as reviewed' : 'dismissed';
        setToast({ message: `${plural(succeeded.length, 'violation')} ${verb}`, type: 'success', isVisible: true });
      }
    },
    [applyStatus]
  );

  const handleGroupAction = useCallback((incident: Incident, action: IncidentAction) => {
    setConfirm({ kind: 'group', incident, action, ids: [...incident.open_violation_ids] });
  }, []);

  // Row actions report on their incident's card, where the row is.
  const handleMemberAction = useCallback(
    (incident: Incident, violation: Violation, action: IncidentAction) => {
      if (action === 'dismiss') {
        setConfirm({ kind: 'member', incident, violation });
      } else {
        void run(incident.incident_id, [violation.id], 'review');
      }
    },
    [run]
  );

  const handleConfirm = useCallback(async () => {
    if (!confirm) return;
    const current = confirm;
    setConfirm(null);
    if (current.kind === 'group') {
      await run(current.incident.incident_id, current.ids, current.action);
    } else {
      await run(current.incident.incident_id, [current.violation.id], 'dismiss');
    }
  }, [confirm, run]);

  const dialog = useMemo(() => {
    if (!confirm) return null;
    if (confirm.kind === 'member') return {};
    const { incident, action, ids } = confirm;
    const what = `${incident.detail_label ?? incident.type_label} on ${cameraHeadline(incident)}, ${formatIncidentSpan(incident.first_at, incident.last_at)}.`;
    return action === 'dismiss'
      ? {
          title: `Dismiss ${plural(ids.length, 'violation')}?`,
          message: what,
          note: `Only the incident's open violations are dismissed. They stay findable under the "Dismissed" status filter.`,
          confirmLabel: `Yes, dismiss ${ids.length}`,
        }
      : {
          title: `Mark ${plural(ids.length, 'violation')} reviewed?`,
          message: what,
          note: `Only the incident's open violations are changed.`,
          confirmLabel: `Mark ${ids.length} reviewed`,
          pendingLabel: 'Saving...',
        };
  }, [confirm]);

  if (isLoading) {
    return <AlertsListSkeleton />;
  }

  if (isError) {
    return (
      <div className="alerts-list__error" role="alert">
        <p className="alerts-list__error-message">Couldn't load alerts. Please try again.</p>
        <button type="button" className="alerts-list__error-retry" onClick={() => refetch()}>
          Retry
        </button>
      </div>
    );
  }

  const incidents = data?.items ?? [];

  if (incidents.length === 0) {
    const hasFilters =
      filters.statuses.length > 0 ||
      filters.dateFrom !== null ||
      filters.dateTo !== null ||
      filters.cameraId !== null ||
      filters.violationType !== '' ||
      filters.severities.length > 0 ||
      filters.area !== null;
    return (
      <div className="alerts-list__empty">
        <p className="alerts-list__empty-message">
          {hasFilters ? 'No violations match your filters' : 'No active violations'}
        </p>
        <p className="alerts-list__empty-hint">
          {hasFilters ? 'Try adjusting your filter criteria.' : 'New detections will appear here automatically.'}
        </p>
      </div>
    );
  }

  return (
    <>
      {data && (
        <p className="alerts-list__grouping">
          {plural(data.total, 'incident')} · {plural(data.violations_total, 'violation')} · repeats within{' '}
          {data.gap_minutes} min on the same camera are grouped
        </p>
      )}

      <div className="alerts-list">
        {incidents.map((incident) => (
          <IncidentCard
            key={incident.incident_id}
            incident={incident}
            statuses={filters.statuses}
            onGroupAction={handleGroupAction}
            onMemberAction={handleMemberAction}
            isPending={!!pending[incident.incident_id]}
            error={errors[incident.incident_id] ?? null}
          />
        ))}
      </div>

      <Pagination
        currentPage={currentPage}
        totalItems={data?.total ?? 0}
        pageSize={pageSize}
        onPageChange={handlePageChange}
        onPageSizeChange={handlePageSizeChange}
        pageSizeOptions={[10, 25, 50]}
        disabled={isFetching}
      />

      <DismissConfirmationDialog
        isOpen={confirm !== null}
        onConfirm={handleConfirm}
        onCancel={() => setConfirm(null)}
        {...dialog}
      />

      <Toast
        message={toast.message}
        type={toast.type}
        isVisible={toast.isVisible}
        onDismiss={() => setToast((prev) => ({ ...prev, isVisible: false }))}
      />
    </>
  );
}
