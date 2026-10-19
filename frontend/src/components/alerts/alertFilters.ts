import type { Device, ViolationsQueryParams } from '../../state/api';
import { typeFilterToParams } from '../../utils/violationLabels';
import type { AlertFilters } from './AlertsFilterSidebar';

/**
 * Sidebar filters -> incidents/violations query params.
 *
 * Every filter is applied by the backend — statuses included, now that it
 * accepts several — so paging and totals count what is actually shown.
 * (Several statuses used to be filtered client-side, page by page.)
 */
export function alertFiltersToParams(
  filters: AlertFilters,
  page: number,
  pageSize: number
): ViolationsQueryParams {
  return {
    status: filters.statuses.length ? [...filters.statuses] : undefined,
    camera_id: filters.cameraId || undefined,
    since: filters.dateFrom ? `${filters.dateFrom}T00:00:00Z` : undefined,
    until: filters.dateTo ? `${filters.dateTo}T23:59:59Z` : undefined,
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
