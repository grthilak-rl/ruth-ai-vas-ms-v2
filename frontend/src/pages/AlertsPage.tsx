import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AlertsList, AlertsFilterSidebar, type AlertFilters } from '../components/alerts';
import {
  DEFAULT_PAGE_SIZE,
  PAGE_SIZE_OPTIONS,
  listStateFromSearch,
  listStateToSearch,
  type AlertsListState,
} from '../components/alerts/alertFilters';
import { useDevicesQuery, useViolationTypesQuery } from '../state';
import {
  getStoredPageSize,
  readScrollPosition,
  rememberListSearch,
  saveScrollPosition,
  storePageSize,
} from '../utils/alertsListMemory';
import './AlertsPage.css';

/**
 * Alerts List Page (F2/E5)
 *
 * Path: /alerts
 *
 * The most critical operator workflow: viewing, triaging, and acting on
 * live violations.
 *
 * Layout:
 * - Left sidebar: Filter controls (Status, Date Range, Camera, Severity, Area, Type)
 * - Main area: summary strip and incidents list
 *
 * The list's state — filters, page, page size, expanded incident — lives in
 * the URL, so opening a violation and coming Back, a refresh, or a shared
 * link all show the same list. Changes replace the history entry rather
 * than push one, so Back leaves the page instead of stepping through
 * filter clicks. The page size is also remembered per browser as the
 * default, and the scroll position per list URL.
 */
export function AlertsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const search = searchParams.toString();
  const defaultPageSize = getStoredPageSize(DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS);

  // Parsed from the string, so the objects only change when the URL does.
  const state = useMemo(
    () => listStateFromSearch(new URLSearchParams(search), defaultPageSize),
    [search, defaultPageSize]
  );

  const update = useCallback(
    (patch: Partial<AlertsListState>) => {
      const next = listStateToSearch({ ...state, ...patch }, defaultPageSize);
      setSearchParams(next, { replace: true });
    },
    [state, defaultPageSize, setSearchParams]
  );

  // "Back to Alerts" on a violation returns to this exact list.
  useEffect(() => {
    rememberListSearch(search);
  }, [search]);

  // Fetch devices for camera filter dropdown
  const { data: devicesData, isLoading: devicesLoading } = useDevicesQuery();
  const cameras = useMemo(() => devicesData?.items ?? [], [devicesData?.items]);

  // Violation families and specific types that occur, for the type dropdown
  const { data: typesData, isLoading: typesLoading } = useViolationTypesQuery();
  const typeOptions = useMemo(() => typesData?.items ?? [], [typesData?.items]);

  const handleFiltersChange = useCallback(
    (filters: AlertFilters) => update({ filters, page: 1, expanded: null }),
    [update]
  );
  const handlePageChange = useCallback((page: number) => update({ page, expanded: null }), [update]);
  const handlePageSizeChange = useCallback(
    (pageSize: number) => {
      storePageSize(pageSize);
      update({ pageSize, page: 1, expanded: null });
    },
    [update]
  );
  const handleToggleExpand = useCallback((expanded: string | null) => update({ expanded }), [update]);

  // Scroll: the list scrolls inside .alerts-page__main, not the window, so
  // it is saved per list URL and restored once that list has rendered.
  // A different URL (new filters, next page) has no saved position, so it
  // starts at the top.
  const mainRef = useRef<HTMLElement>(null);
  const restoredFor = useRef<string | null>(null);
  const frame = useRef<number | null>(null);

  const handleScroll = useCallback(() => {
    if (restoredFor.current !== search) return; // don't record the jump before restoring
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      if (mainRef.current) saveScrollPosition(search, mainRef.current.scrollTop);
    });
  }, [search]);

  const handleListReady = useCallback(() => {
    if (restoredFor.current === search || !mainRef.current) return;
    restoredFor.current = search;
    mainRef.current.scrollTop = readScrollPosition(search);
  }, [search]);

  useEffect(
    () => () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    },
    []
  );

  return (
    <div className="alerts-page">
      <AlertsFilterSidebar
        filters={state.filters}
        onFiltersChange={handleFiltersChange}
        cameras={cameras}
        camerasLoading={devicesLoading}
        typeOptions={typeOptions}
        typeOptionsLoading={typesLoading}
      />
      <main className="alerts-page__main" ref={mainRef} onScroll={handleScroll}>
        <section className="alerts-page__content">
          <AlertsList
            filters={state.filters}
            page={state.page}
            pageSize={state.pageSize}
            expanded={state.expanded}
            onPageChange={handlePageChange}
            onPageSizeChange={handlePageSizeChange}
            onToggleExpand={handleToggleExpand}
            onReady={handleListReady}
          />
        </section>
      </main>
    </div>
  );
}
