import { useState, useCallback, useMemo, useLayoutEffect } from 'react';
import { useBulkViolationAction, useIncidentsQuery } from '../../state';
import {
  ApiError,
  BULK_LIMIT,
  fetchIncidents,
  type DismissReason,
  type Incident,
  type Violation,
  type ViolationBulkFilter,
  type ViolationBulkRequest,
} from '../../state/api';
import { IncidentCard, type IncidentAction } from './IncidentCard';
import { DismissConfirmationDialog } from './DismissConfirmationDialog';
import { DismissReasonDialog } from './DismissReasonDialog';
import { SummaryStrip } from './SummaryStrip';
import { Toast, type ToastType } from './Toast';
import { AlertsListSkeleton } from './AlertsListSkeleton';
import { ExportDialog } from './ExportDialog';
import { Pagination } from '../ui';
import {
  alertFiltersToParams,
  frozenOpenSelection,
  PAGE_SIZE_OPTIONS,
  type AlertFilters,
} from './alertFilters';
import { cameraHeadline, formatIncidentSpan } from '../../utils/violationDisplay';
import { summarizeBulkResult } from './bulkResult';
import './AlertsList.css';

const plural = (n: number, word: string) =>
  `${n.toLocaleString('en-US')} ${word}${n === 1 ? '' : 's'}`;

const RANGE_LABELS: Record<AlertFilters['range'], string> = {
  today: 'Today',
  '7d': 'Last 7 days',
  '30d': 'Last 30 days',
  all: 'All time',
  custom: 'Custom range',
};

/** What an action applies to: listed violations, or every open one matching a frozen filter. */
type Target =
  | { kind: 'ids'; ids: string[] }
  | { kind: 'filter'; filter: ViolationBulkFilter; expected: number; incidents: number };

const targetCount = (target: Target) => (target.kind === 'ids' ? target.ids.length : target.expected);

/** What a confirmation dialog is about to do. */
type PendingAction =
  | { kind: 'review'; target: Target; cardKey: string | null; title: string; message: string }
  | { kind: 'dismiss'; target: Target; cardKey: string | null; context: string };

/**
 * The bulk selection, kept per set of filters (so it survives paging and
 * is dropped when a filter changes, since filters change what an incident
 * contains). Either incidents picked by hand on any page — each holding the
 * open violations it had when picked — or "all matching this filter".
 */
type Selection =
  | {
      mode: 'ids';
      key: string;
      ids: Record<string, string[]>;
      /** Set when leaving "all matching" narrowed the selection to this page. */
      narrowed?: boolean;
    }
  | { mode: 'all'; key: string };

function describe(incident: Incident): string {
  return `${incident.detail_label ?? incident.type_label} on ${cameraHeadline(incident)}, ${formatIncidentSpan(incident.first_at, incident.last_at)}.`;
}

function filterMessage(target: Extract<Target, { kind: 'filter' }>): string {
  const asOf = new Date(target.filter.until).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  return `Every open violation matching the current filters, up to ${asOf}: ${plural(target.expected, 'open violation')} in ${plural(target.incidents, 'incident')}. Violations arriving after that are not included.`;
}

function confirmationFor(
  kind: IncidentAction,
  target: Target,
  cardKey: string | null,
  message: string
): PendingAction {
  const n = targetCount(target);
  return kind === 'dismiss'
    ? { kind: 'dismiss', target, cardKey, context: message }
    : { kind: 'review', target, cardKey, title: `Mark ${plural(n, 'violation')} reviewed?`, message };
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
 * Every action — a card's group action, a selection, "all matching", or one
 * row — goes through POST /violations/bulk: one request, the same
 * validation, and false-alarm dismissals always reach the labelling export.
 * Ids are fixed when the incident is selected, and "all matching" is a
 * filter frozen when the dialog opens and re-counted by the server, so
 * repeats arriving meanwhile are never swept in.
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

  // The selection belongs to the filters it was made under, not the page:
  // paging keeps it, any filter change drops it. Keyed on the filter state
  // rather than the query, whose relative "since" moves every minute.
  const filtersKey = JSON.stringify(filters);
  const [selection, setSelection] = useState<Selection>({ mode: 'ids', key: filtersKey, ids: {} });
  const current = useMemo<Selection>(
    () => (selection.key === filtersKey ? selection : { mode: 'ids', key: filtersKey, ids: {} }),
    [selection, filtersKey]
  );
  const allMatching = current.mode === 'all';
  const picked = useMemo(
    () => (current.mode === 'ids' ? current.ids : {}),
    [current]
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
  const showToast = useCallback(
    (message: string, type: ToastType) => setToast({ message, type, isVisible: true }),
    []
  );

  const incidents = useMemo(() => data?.items ?? [], [data?.items]);
  // Only incidents with something open are selectable — by their own
  // checkbox and by "Select page" alike — since review and dismiss only
  // ever change open violations. The snapshot export without a selection
  // still covers reviewed and dismissed ones, through the filters.
  const selectable = useMemo(() => incidents.filter((i) => i.open_count > 0), [incidents]);
  const isSelected = useCallback(
    (incident: Incident) => (allMatching ? incident.open_count > 0 : !!picked[incident.incident_id]),
    [allMatching, picked]
  );
  const selectedIncidentIds = useMemo(() => Object.keys(picked), [picked]);
  const selectedIds = useMemo(() => [...new Set(Object.values(picked).flat())], [picked]);
  // Open violations matching the filters (status forced open), all pages.
  // Absent from older backends, which then offer no "select all".
  const openMatching = data?.open_violations_total;
  const pageAllSelected = selectable.length > 0 && selectable.every(isSelected);
  const overLimit = allMatching && (openMatching ?? 0) > BULK_LIMIT;

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
      confidences: queryParams.confidence ?? null,
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
        const id = incident.incident_id;
        if (prev.key === filtersKey && prev.mode === 'all') {
          // Unticking one card while "all matching" is on falls back to
          // this page's open incidents minus that card — this page only.
          // "Select all" had already replaced any picks on other pages, so
          // the bar says the selection narrowed rather than dropping them
          // silently.
          const ids = Object.fromEntries(
            selectable.filter((i) => i.incident_id !== id).map((i) => [i.incident_id, [...i.open_violation_ids]])
          );
          return { mode: 'ids', key: filtersKey, ids, narrowed: true };
        }
        const ids = { ...(prev.key === filtersKey && prev.mode === 'ids' ? prev.ids : {}) };
        if (ids[id]) delete ids[id];
        else ids[id] = [...incident.open_violation_ids];
        return { mode: 'ids', key: filtersKey, ids };
      });
    },
    [filtersKey, selectable]
  );

  // Adds or removes this page's open incidents; other pages' picks stay.
  const toggleSelectPage = useCallback(() => {
    setSelection((prev) => {
      if (prev.key === filtersKey && prev.mode === 'all') return { mode: 'ids', key: filtersKey, ids: {} };
      const ids = { ...(prev.key === filtersKey && prev.mode === 'ids' ? prev.ids : {}) };
      for (const incident of selectable) {
        if (pageAllSelected) delete ids[incident.incident_id];
        else ids[incident.incident_id] ??= [...incident.open_violation_ids];
      }
      return { mode: 'ids', key: filtersKey, ids };
    });
  }, [filtersKey, pageAllSelected, selectable]);

  const selectAllMatching = useCallback(
    () => setSelection({ mode: 'all', key: filtersKey }),
    [filtersKey]
  );
  const clearSelection = useCallback(
    () => setSelection({ mode: 'ids', key: filtersKey, ids: {} }),
    [filtersKey]
  );

  const run = useCallback(
    async (action: PendingAction, reason?: DismissReason, note?: string) => {
      const { target, cardKey } = action;
      const key = cardKey ?? '__bulk__';
      const kind: IncidentAction = action.kind;
      let next: PendingAction | null = null;
      setErrors((prev) => {
        const rest = { ...prev };
        delete rest[key];
        return rest;
      });
      setPending((prev) => ({ ...prev, [key]: true }));
      setIsSaving(true);
      try {
        const common = { action: kind, dismiss_reason: reason, note };
        const request: ViolationBulkRequest =
          target.kind === 'ids'
            ? { ...common, ids: target.ids }
            : { ...common, filter: target.filter, expected_count: target.expected };
        const result = await bulk(request);
        const failedExport = (result.labelling?.failed ?? 0) > 0;
        showToast(summarizeBulkResult(result, kind), failedExport ? 'error' : 'success');
        if (cardKey && result.skipped.length) {
          setErrors((prev) => ({
            ...prev,
            [cardKey]: `${result.skipped.length} of ${targetCount(target)} were already reviewed or dismissed and were left as they were.`,
          }));
        }
        if (!cardKey) clearSelection();
      } catch (err) {
        const currentCount = Number(err instanceof ApiError ? err.details?.current_count : NaN);
        if (err instanceof ApiError && err.status === 409 && target.kind === 'filter' && currentCount > 0) {
          // Something changed between counting and saving. Nothing was
          // changed; ask again with the number that matches now.
          const retarget = { ...target, expected: currentCount };
          next = confirmationFor(
            kind,
            retarget,
            cardKey,
            `The number changed while this was open, and nothing has been changed yet. ${filterMessage(retarget)}`
          );
        } else if (err instanceof ApiError && err.status === 409 && target.kind === 'filter') {
          showToast('No open violations match these filters any more. Nothing was changed.', 'error');
          clearSelection();
        } else {
          const message = err instanceof Error ? err.message : "Couldn't save. Please try again.";
          if (cardKey) setErrors((prev) => ({ ...prev, [cardKey]: message }));
          else showToast(message, 'error');
        }
      } finally {
        setPending((prev) => {
          const rest = { ...prev };
          delete rest[key];
          return rest;
        });
        setIsSaving(false);
        setDialog(next);
      }
    },
    [bulk, clearSelection, showToast]
  );

  const handleGroupAction = useCallback((incident: Incident, action: IncidentAction) => {
    const target: Target = { kind: 'ids', ids: [...incident.open_violation_ids] };
    setDialog(confirmationFor(action, target, incident.incident_id, describe(incident)));
  }, []);

  // Row actions report on their incident's card, where the row is.
  const handleMemberAction = useCallback(
    (incident: Incident, violation: Violation, action: IncidentAction) => {
      const target: Target = { kind: 'ids', ids: [violation.id] };
      if (action === 'dismiss') {
        setDialog(
          confirmationFor(
            'dismiss',
            target,
            incident.incident_id,
            `One violation at ${new Date(violation.timestamp).toLocaleTimeString('en-US')}: ${describe(incident)}`
          )
        );
      } else {
        void run(confirmationFor('review', target, incident.incident_id, ''));
      }
    },
    [run]
  );

  const handleBulk = useCallback(
    async (action: IncidentAction) => {
      if (!allMatching) {
        const message = `${plural(selectedIds.length, 'open violation')} in ${plural(selectedIncidentIds.length, 'selected incident')}.`;
        setDialog(confirmationFor(action, { kind: 'ids', ids: selectedIds }, null, message));
        return;
      }
      // "All matching": freeze the range now, then count exactly what that
      // frozen filter will change, so the dialog states the real total.
      const { filter, countParams } = frozenOpenSelection(filters);
      setPending((prev) => ({ ...prev, __bulk__: true }));
      try {
        const counted = await fetchIncidents(countParams);
        // Status is forced open here, so every counted violation is open.
        const n = counted.violations_total;
        if (n === 0) {
          showToast('No open violations match these filters any more.', 'error');
          clearSelection();
        } else if (n > BULK_LIMIT) {
          showToast(
            `${plural(n, 'open violation')} match; at most ${BULK_LIMIT.toLocaleString('en-US')} can be changed at once. Narrow the filters.`,
            'error'
          );
        } else {
          const target: Target = { kind: 'filter', filter, expected: n, incidents: counted.total };
          setDialog(confirmationFor(action, target, null, filterMessage(target)));
        }
      } catch (err) {
        showToast(err instanceof Error ? err.message : "Couldn't count the matching violations.", 'error');
      } finally {
        setPending((prev) => {
          const rest = { ...prev };
          delete rest.__bulk__;
          return rest;
        });
      }
    },
    [allMatching, clearSelection, filters, selectedIds, selectedIncidentIds.length, showToast]
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

  const hasSelection = allMatching || selectedIncidentIds.length > 0;
  // Exact totals on every button: picked violations, or all that match.
  const actionCount = allMatching ? (openMatching ?? 0) : selectedIds.length;
  const actionsDisabled = !!pending.__bulk__ || actionCount === 0 || overLimit;
  const actionsTitle = overLimit
    ? `More than ${BULK_LIMIT.toLocaleString('en-US')} open violations match. Narrow the filters to act on them together.`
    : actionCount === 0
      ? 'The selected incidents have no open violations'
      : undefined;
  const moreToSelect =
    !allMatching && pageAllSelected && openMatching !== undefined && openMatching > selectedIds.length;

  return (
    <>
      {strip}

      <div className="alerts-list__bulk" role="toolbar" aria-label="Bulk actions">
        <label className="alerts-list__bulk-select">
          <input
            type="checkbox"
            checked={pageAllSelected}
            onChange={toggleSelectPage}
            disabled={selectable.length === 0}
          />
          <span>Select page</span>
        </label>
        {hasSelection ? (
          <>
            <span className="alerts-list__bulk-count" aria-live="polite">
              {allMatching
                ? `All ${plural(openMatching ?? 0, 'open violation')} matching these filters selected`
                : `${plural(selectedIncidentIds.length, 'incident')} · ${plural(selectedIds.length, 'open violation')} selected`}
            </span>
            <button
              type="button"
              className="alerts-list__bulk-action alerts-list__bulk-action--review"
              onClick={() => void handleBulk('review')}
              disabled={actionsDisabled}
              title={actionsTitle}
            >
              Mark {actionCount.toLocaleString('en-US')} reviewed
            </button>
            <button
              type="button"
              className="alerts-list__bulk-action"
              onClick={() => void handleBulk('dismiss')}
              disabled={actionsDisabled}
              title={actionsTitle}
            >
              Dismiss {actionCount.toLocaleString('en-US')}…
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
        {moreToSelect && (
          <div className="alerts-list__bulk-more">
            All open incidents on this page are selected.{' '}
            <button type="button" className="alerts-list__bulk-link" onClick={selectAllMatching}>
              Select all {plural(openMatching, 'open violation')} matching these filters
            </button>
            {openMatching > BULK_LIMIT && (
              <span className="alerts-list__bulk-hint">
                {' '}(over the {BULK_LIMIT.toLocaleString('en-US')} that can be changed at once)
              </span>
            )}
          </div>
        )}
        {current.mode === 'ids' && current.narrowed && selectedIncidentIds.length > 0 && (
          <div className="alerts-list__bulk-more" role="status">
            Now only this page's incidents are selected; other pages are no longer included.
          </div>
        )}
        {allMatching && (
          <div className="alerts-list__bulk-more">
            Includes violations on every page.{' '}
            <button type="button" className="alerts-list__bulk-link" onClick={clearSelection}>
              Clear selection
            </button>
          </div>
        )}
      </div>

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
            selected={isSelected(incident)}
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
        count={dialog ? targetCount(dialog.target) : 0}
        context={dialog?.kind === 'dismiss' ? dialog.context : undefined}
        isPending={isSaving}
        onCancel={() => setDialog(null)}
        onConfirm={(reason, note) => dialog && void run(dialog, reason, note)}
      />

      <DismissConfirmationDialog
        isOpen={dialog?.kind === 'review'}
        isPending={isSaving}
        onCancel={() => setDialog(null)}
        onConfirm={() => dialog && void run(dialog)}
        title={dialog?.kind === 'review' ? dialog.title : undefined}
        message={dialog?.kind === 'review' ? dialog.message : undefined}
        note="Only open violations are changed; anything already reviewed or dismissed is left as it is."
        confirmLabel={`Mark ${(dialog ? targetCount(dialog.target) : 0).toLocaleString('en-US')} reviewed`}
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
          incidentIds={!allMatching && selectedIncidentIds.length > 0 ? selectedIncidentIds : null}
          onClose={() => setExportOpen(false)}
        />
      )}
    </>
  );
}
