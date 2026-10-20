import { useState, useCallback, useMemo, useLayoutEffect } from 'react';
import { useBulkViolationAction, useIncidentsQuery } from '../../state';
import type { DismissReason, Incident, Violation } from '../../state/api';
import { IncidentCard, type IncidentAction } from './IncidentCard';
import { DismissConfirmationDialog } from './DismissConfirmationDialog';
import { DismissReasonDialog } from './DismissReasonDialog';
import { SummaryStrip } from './SummaryStrip';
import { Toast, type ToastType } from './Toast';
import { AlertsListSkeleton } from './AlertsListSkeleton';
import { ExportDialog } from './ExportDialog';
import { Pagination } from '../ui';
import { alertFiltersToParams, PAGE_SIZE_OPTIONS, type AlertFilters } from './alertFilters';
import { cameraHeadline, formatIncidentSpan } from '../../utils/violationDisplay';
import { summarizeBulkResult } from './bulkResult';
import './AlertsList.css';

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

const RANGE_LABELS: Record<AlertFilters['range'], string> = {
  today: 'Today',
  '7d': 'Last 7 days',
  '30d': 'Last 30 days',
  all: 'All time',
  custom: 'Custom range',
};

/** What a confirmation dialog is about to do. */
type PendingAction =
  | { kind: 'review'; ids: string[]; cardKey: string | null; title: string; message: string }
  | { kind: 'dismiss'; ids: string[]; cardKey: string | null; context: string };

function describe(incident: Incident): string {
  return `${incident.detail_label ?? incident.type_label} on ${cameraHeadline(incident)}, ${formatIncidentSpan(incident.first_at, incident.last_at)}.`;
}

interface AlertsListProps {
  filters: AlertFilters;
  page: number;
  pageSize: number;
  /** The incident expanded to list its violations */
  expanded: string | null;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  onToggleExpand: (incidentId: string | null) => void;
  /** Called once the list has rendered its data, so the page can restore scroll */
  onReady?: () => void;
}

/**
 * Alerts List — violations grouped into incidents.
 *
 * Filters, page, page size and the expanded incident are owned by the page
 * (in the URL); this component owns the selection and the action dialogs.
 *
 * Every action — a card's group action, a selected batch, or one row —
 * goes through POST /violations/bulk: one request, the same validation, and
 * false-alarm dismissals always reach the labelling export. Ids are fixed
 * when the dialog opens, so repeats arriving meanwhile are not swept in.
 */
export function AlertsList({
  filters,
  page,
  pageSize,
  expanded,
  onPageChange,
  onPageSizeChange,
  onToggleExpand,
  onReady,
}: AlertsListProps) {
  const queryParams = useMemo(
    () => alertFiltersToParams(filters, page, pageSize),
    [filters, page, pageSize]
  );
  const { data, isLoading, isFetching, isError, refetch } = useIncidentsQuery(queryParams);
  const bulk = useBulkViolationAction();

  // Selection belongs to the page of results it was made on.
  const selectionKey = JSON.stringify(queryParams);
  const [selection, setSelection] = useState<{ key: string; ids: Record<string, string[]> }>({
    key: selectionKey,
    ids: {},
  });
  const selected = useMemo(
    () => (selection.key === selectionKey ? selection.ids : {}),
    [selection, selectionKey]
  );

  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [dialog, setDialog] = useState<PendingAction | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: ToastType; isVisible: boolean }>({
    message: '',
    type: 'success',
    isVisible: false,
  });

  const incidents = useMemo(() => data?.items ?? [], [data?.items]);
  // Every incident is selectable, not just those with open violations: the
  // evidence export covers reviewed and dismissed ones too, and a dismissed
  // incident is often exactly what the AI engineer wants to look at. The
  // bulk review/dismiss actions still only touch open violations, so they
  // are disabled when a selection contains none.
  const selectable = incidents;
  const selectedIncidents = Object.keys(selected).length;
  const selectedIds = useMemo(() => [...new Set(Object.values(selected).flat())], [selected]);
  const selectedIncidentIds = useMemo(() => Object.keys(selected), [selected]);

  // The same filters the list is showing, in the export's names. The
  // server regroups incidents from these, so they must match or a
  // selected incident key will not resolve.
  const exportFilters = useMemo(
    () => ({
      // status may be a single value or an array in the query params;
      // the export body always takes a list.
      statuses:
        queryParams.status == null
          ? null
          : Array.isArray(queryParams.status)
            ? [...queryParams.status]
            : [queryParams.status],
      camera_id: queryParams.camera_id ?? null,
      since: queryParams.since ?? null,
      until: queryParams.until ?? null,
      violation_type: queryParams.type ?? null,
      type_detail: queryParams.type_detail ?? null,
      severities: queryParams.severity ?? null,
      area: queryParams.area ?? null,
    }),
    [queryParams]
  );

  // Tell the page when there is something to scroll to.
  useLayoutEffect(() => {
    if (data) onReady?.();
  }, [data, onReady]);

  const toggleSelect = useCallback(
    (incident: Incident) => {
      setSelection((prev) => {
        const ids = prev.key === selectionKey ? { ...prev.ids } : {};
        if (ids[incident.incident_id]) delete ids[incident.incident_id];
        else ids[incident.incident_id] = [...incident.open_violation_ids];
        return { key: selectionKey, ids };
      });
    },
    [selectionKey]
  );

  const allSelected = selectable.length > 0 && selectable.every((i) => selected[i.incident_id]);
  const toggleSelectPage = useCallback(() => {
    setSelection({
      key: selectionKey,
      ids: allSelected
        ? {}
        : Object.fromEntries(selectable.map((i) => [i.incident_id, [...i.open_violation_ids]])),
    });
  }, [allSelected, selectable, selectionKey]);

  const clearSelection = useCallback(() => setSelection({ key: selectionKey, ids: {} }), [selectionKey]);

  const run = useCallback(
    async (
      action: 'review' | 'dismiss',
      ids: string[],
      cardKey: string | null,
      reason?: DismissReason,
      note?: string
    ) => {
      const key = cardKey ?? '__bulk__';
      setErrors((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      setPending((prev) => ({ ...prev, [key]: true }));
      setIsSaving(true);
      try {
        const result = await bulk({ ids, action, dismiss_reason: reason, note });
        const failedExport = (result.labelling?.failed ?? 0) > 0;
        setToast({
          message: summarizeBulkResult(result, action),
          type: failedExport ? 'error' : 'success',
          isVisible: true,
        });
        if (cardKey && result.skipped.length) {
          setErrors((prev) => ({
            ...prev,
            [cardKey]: `${result.skipped.length} of ${ids.length} were already reviewed or dismissed and were left as they were.`,
          }));
        }
        if (!cardKey) clearSelection();
      } catch (err) {
        const message = err instanceof Error ? err.message : "Couldn't save. Please try again.";
        if (cardKey) setErrors((prev) => ({ ...prev, [cardKey]: message }));
        else setToast({ message, type: 'error', isVisible: true });
      } finally {
        setPending((prev) => {
          const next = { ...prev };
          delete next[key];
          return next;
        });
        setIsSaving(false);
        setDialog(null);
      }
    },
    [bulk, clearSelection]
  );

  const handleGroupAction = useCallback((incident: Incident, action: IncidentAction) => {
    const ids = [...incident.open_violation_ids];
    setDialog(
      action === 'dismiss'
        ? { kind: 'dismiss', ids, cardKey: incident.incident_id, context: describe(incident) }
        : {
            kind: 'review',
            ids,
            cardKey: incident.incident_id,
            title: `Mark ${plural(ids.length, 'violation')} reviewed?`,
            message: describe(incident),
          }
    );
  }, []);

  // Row actions report on their incident's card, where the row is.
  const handleMemberAction = useCallback(
    (incident: Incident, violation: Violation, action: IncidentAction) => {
      if (action === 'dismiss') {
        setDialog({
          kind: 'dismiss',
          ids: [violation.id],
          cardKey: incident.incident_id,
          context: `One violation at ${new Date(violation.timestamp).toLocaleTimeString('en-US')}: ${describe(incident)}`,
        });
      } else {
        void run('review', [violation.id], incident.incident_id);
      }
    },
    [run]
  );

  const handleBulk = useCallback(
    (action: IncidentAction) => {
      const message = `${plural(selectedIds.length, 'open violation')} in ${plural(selectedIncidents, 'selected incident')}.`;
      setDialog(
        action === 'dismiss'
          ? { kind: 'dismiss', ids: selectedIds, cardKey: null, context: message }
          : {
              kind: 'review',
              ids: selectedIds,
              cardKey: null,
              title: `Mark ${plural(selectedIds.length, 'violation')} reviewed?`,
              message,
            }
      );
    },
    [selectedIds, selectedIncidents]
  );

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

  const strip = data && (
    <SummaryStrip
      summary={data.summary}
      incidents={data.total}
      violations={data.violations_total}
      gapMinutes={data.gap_minutes}
      rangeLabel={RANGE_LABELS[filters.range]}
    />
  );

  if (incidents.length === 0) {
    return (
      <>
        {strip}
        <div className="alerts-list__empty">
          <p className="alerts-list__empty-message">No violations match your filters</p>
          <p className="alerts-list__empty-hint">
            {filters.range === 'all'
              ? 'Try adjusting your filter criteria.'
              : 'Try widening the date range, or adjusting other filters.'}
          </p>
        </div>
      </>
    );
  }

  return (
    <>
      {strip}

      {selectable.length > 0 && (
        <div className="alerts-list__bulk" role="toolbar" aria-label="Bulk actions">
          <label className="alerts-list__bulk-select">
            <input type="checkbox" checked={allSelected} onChange={toggleSelectPage} />
            <span>Select page</span>
          </label>
          {selectedIncidents > 0 ? (
            <>
              <span className="alerts-list__bulk-count">
                {plural(selectedIncidents, 'incident')} · {plural(selectedIds.length, 'open violation')}
              </span>
              <button
                type="button"
                className="alerts-list__bulk-action alerts-list__bulk-action--review"
                onClick={() => handleBulk('review')}
                disabled={!!pending.__bulk__ || selectedIds.length === 0}
                title={
                  selectedIds.length === 0
                    ? 'The selected incidents have no open violations'
                    : undefined
                }
              >
                Mark reviewed
              </button>
              <button
                type="button"
                className="alerts-list__bulk-action"
                onClick={() => handleBulk('dismiss')}
                disabled={!!pending.__bulk__ || selectedIds.length === 0}
                title={
                  selectedIds.length === 0
                    ? 'The selected incidents have no open violations'
                    : undefined
                }
              >
                Dismiss…
              </button>
              <button
                type="button"
                className="alerts-list__bulk-action"
                onClick={() => setExportOpen(true)}
              >
                Download snapshots…
              </button>
              <button type="button" className="alerts-list__bulk-clear" onClick={clearSelection}>
                Clear
              </button>
            </>
          ) : (
            <>
              <span className="alerts-list__bulk-hint">
                Select incidents to act on their open violations together
              </span>
              <button
                type="button"
                className="alerts-list__bulk-action"
                onClick={() => setExportOpen(true)}
              >
                Download snapshots…
              </button>
            </>
          )}
        </div>
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
            expanded={expanded === incident.incident_id}
            onToggleExpand={(i) => onToggleExpand(expanded === i.incident_id ? null : i.incident_id)}
            selected={!!selected[incident.incident_id]}
            onToggleSelect={toggleSelect}
          />
        ))}
      </div>

      <Pagination
        currentPage={page}
        totalItems={data?.total ?? 0}
        pageSize={pageSize}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
        pageSizeOptions={PAGE_SIZE_OPTIONS}
        disabled={isFetching}
      />

      <DismissReasonDialog
        isOpen={dialog?.kind === 'dismiss'}
        count={dialog?.ids.length ?? 0}
        context={dialog?.kind === 'dismiss' ? dialog.context : undefined}
        isPending={isSaving}
        onCancel={() => setDialog(null)}
        onConfirm={(reason, note) =>
          dialog && void run('dismiss', dialog.ids, dialog.cardKey, reason, note)
        }
      />

      <DismissConfirmationDialog
        isOpen={dialog?.kind === 'review'}
        isPending={isSaving}
        onCancel={() => setDialog(null)}
        onConfirm={() => dialog && void run('review', dialog.ids, dialog.cardKey)}
        title={dialog?.kind === 'review' ? dialog.title : undefined}
        message={dialog?.kind === 'review' ? dialog.message : undefined}
        note="Only open violations are changed; anything already reviewed or dismissed is left as it is."
        confirmLabel={`Mark ${dialog?.ids.length ?? 0} reviewed`}
        pendingLabel="Saving..."
      />

      <Toast
        message={toast.message}
        type={toast.type}
        isVisible={toast.isVisible}
        onDismiss={() => setToast((prev) => ({ ...prev, isVisible: false }))}
      />

      {exportOpen && (
        <ExportDialog
          filters={exportFilters}
          incidentIds={selectedIncidentIds.length > 0 ? selectedIncidentIds : null}
          onClose={() => setExportOpen(false)}
        />
      )}
    </>
  );
}
