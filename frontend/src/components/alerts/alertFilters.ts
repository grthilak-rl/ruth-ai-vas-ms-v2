import type { Device, Severity, ViolationStatus, ViolationsQueryParams } from '../../state/api';
import { typeFilterToParams } from '../../utils/violationLabels';
import { SEVERITY_LEVELS } from '../../utils/violationDisplay';

/**
 * Filter state interface
 */
export interface AlertFilters {
  /** Selected statuses (empty = all) */
  statuses: ViolationStatus[];
  /**
   * Date range. Relative ranges ("last 7 days") are resolved when the list
   * is fetched, so a bookmarked or shared link stays relative instead of
   * freezing the dates it was made on.
   */
  range: DateRange;
  /** Custom range start, YYYY-MM-DD in local time (range === 'custom') */
  dateFrom: string | null;
  /** Custom range end, YYYY-MM-DD in local time, inclusive (range === 'custom') */
  dateTo: string | null;
  /** Selected camera ID (null = all) */
  cameraId: string | null;
  /**
   * Selected violation type ('' = all): a family ('ppe_violation') or one
   * specific type ('ppe_violation:missing_gloves'). See violationLabels.
   */
  violationType: string;
  /** Selected severities (empty = all) */
  severities: Severity[];
  /** Selected camera area / manway (null = all) */
  area: string | null;
}


export type DateRange = 'today' | '7d' | '30d' | 'all' | 'custom';

/**
 * Default filter state: open violations from the last 7 days. The window
 * keeps incident grouping cheap as history grows; widen it with the date
 * filter.
 */
export const DEFAULT_FILTERS: AlertFilters = {
  statuses: ['open'], // Default to open violations
  range: '7d',
  dateFrom: null,
  dateTo: null,
  cameraId: null,
  violationType: '',
  severities: [],
  area: null,
};

export const PAGE_SIZE_OPTIONS = [10, 25, 50];
export const DEFAULT_PAGE_SIZE = 10;

const STATUSES: ViolationStatus[] = ['open', 'reviewed', 'dismissed', 'resolved'];
const RANGES: DateRange[] = ['today', '7d', '30d', 'all', 'custom'];
const DAY_MS = 24 * 60 * 60 * 1000;

function parseLocalDate(value: string | null): Date | null {
  const match = value ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(value) : null;
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * The range as timestamps, in the browser's time zone.
 *
 * The old presets built "today" from local midnight via toISOString(),
 * which in IST (UTC+5:30) is the previous day — "Today" began yesterday —
 * and then read those dates as UTC days. Here a relative range counts back
 * from now, rounded to the minute so the query key holds still between
 * polls, and custom dates are whole local days.
 */
export function resolveDateRange(
  filters: Pick<AlertFilters, 'range' | 'dateFrom' | 'dateTo'>,
  now: Date = new Date()
): { since?: string; until?: string } {
  const minute = new Date(Math.floor(now.getTime() / 60_000) * 60_000);
  switch (filters.range) {
    case 'today':
      return { since: new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString() };
    case '7d':
      return { since: new Date(minute.getTime() - 7 * DAY_MS).toISOString() };
    case '30d':
      return { since: new Date(minute.getTime() - 30 * DAY_MS).toISOString() };
    case 'all':
      return {};
    case 'custom': {
      const from = parseLocalDate(filters.dateFrom);
      const to = parseLocalDate(filters.dateTo);
      return {
        since: from?.toISOString(),
        // Inclusive end: the last millisecond of that local day.
        until: to ? new Date(new Date(to.getFullYear(), to.getMonth(), to.getDate() + 1).getTime() - 1).toISOString() : undefined,
      };
    }
  }
}

/**
 * Sidebar filters -> incidents/violations query params. Every filter is
 * applied by the backend, so paging and totals count what is shown.
 */
export function alertFiltersToParams(
  filters: AlertFilters,
  page: number,
  pageSize: number,
  now: Date = new Date()
): ViolationsQueryParams {
  const { since, until } = resolveDateRange(filters, now);
  return {
    status: filters.statuses.length ? [...filters.statuses] : undefined,
    camera_id: filters.cameraId || undefined,
    since,
    until,
    severity: filters.severities.length ? [...filters.severities] : undefined,
    area: filters.area || undefined,
    ...typeFilterToParams(filters.violationType),
    offset: (page - 1) * pageSize,
    limit: pageSize,
  };
}

/** Distinct camera areas (manways), sorted, for the Area filter. */
export function cameraAreas(cameras: Pick<Device, 'manway'>[]): string[] {
  const areas = new Set<string>();
  for (const camera of cameras) {
    const area = camera.manway?.trim();
    if (area) areas.add(area);
  }
  return [...areas].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

// ============================================================================
// URL state
// ============================================================================
// The list's filters, page, page size and expanded incident live in the
// query string, so Back from a violation, a refresh and a shared link all
// restore it. Defaults are left out to keep URLs short:
//
//   ?status=open&status=reviewed&range=30d&severity=critical&area=REFORMER1
//    &type=ppe_violation:missing_gloves&camera=<id>&page=3&per_page=25&open=<incident>
//
// status=any means "no status filter" (an empty selection), since an absent
// status means the default (open).

export interface AlertsListState {
  filters: AlertFilters;
  page: number;
  pageSize: number;
  /** The expanded incident, if any */
  expanded: string | null;
}

export function listStateFromSearch(search: URLSearchParams, defaultPageSize = DEFAULT_PAGE_SIZE): AlertsListState {
  const statusValues = search.getAll('status');
  const statuses = statusValues.includes('any')
    ? []
    : statusValues.length
      ? STATUSES.filter((s) => statusValues.includes(s))
      : [...DEFAULT_FILTERS.statuses];
  const range = search.get('range') as DateRange | null;
  const page = Number.parseInt(search.get('page') ?? '', 10);
  const perPage = Number.parseInt(search.get('per_page') ?? '', 10);

  return {
    filters: {
      statuses,
      range: range && RANGES.includes(range) ? range : DEFAULT_FILTERS.range,
      dateFrom: parseLocalDate(search.get('from')) ? search.get('from') : null,
      dateTo: parseLocalDate(search.get('to')) ? search.get('to') : null,
      cameraId: search.get('camera') || null,
      violationType: search.get('type') ?? '',
      severities: SEVERITY_LEVELS.filter((level) => search.getAll('severity').includes(level)) as Severity[],
      area: search.get('area') || null,
    },
    page: page >= 1 ? page : 1,
    pageSize: PAGE_SIZE_OPTIONS.includes(perPage)
      ? perPage
      : PAGE_SIZE_OPTIONS.includes(defaultPageSize)
        ? defaultPageSize
        : DEFAULT_PAGE_SIZE,
    expanded: search.get('open') || null,
  };
}

export function listStateToSearch(state: AlertsListState, defaultPageSize = DEFAULT_PAGE_SIZE): URLSearchParams {
  const { filters } = state;
  const search = new URLSearchParams();
  const isDefaultStatus =
    filters.statuses.length === DEFAULT_FILTERS.statuses.length &&
    filters.statuses.every((s) => DEFAULT_FILTERS.statuses.includes(s));
  if (filters.statuses.length === 0) search.append('status', 'any');
  else if (!isDefaultStatus) filters.statuses.forEach((s) => search.append('status', s));
  if (filters.range !== DEFAULT_FILTERS.range) search.set('range', filters.range);
  if (filters.range === 'custom') {
    if (filters.dateFrom) search.set('from', filters.dateFrom);
    if (filters.dateTo) search.set('to', filters.dateTo);
  }
  if (filters.cameraId) search.set('camera', filters.cameraId);
  if (filters.violationType) search.set('type', filters.violationType);
  filters.severities.forEach((level) => search.append('severity', level));
  if (filters.area) search.set('area', filters.area);
  if (state.page > 1) search.set('page', String(state.page));
  if (state.pageSize !== defaultPageSize) search.set('per_page', String(state.pageSize));
  if (state.expanded) search.set('open', state.expanded);
  return search;
}
