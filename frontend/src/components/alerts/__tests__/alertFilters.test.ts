import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { buildQueryString } from '../../../state/api/violations.api';
import {
  DEFAULT_FILTERS,
  alertFiltersToParams,
  cameraAreas,
  listStateFromSearch,
  listStateToSearch,
  resolveDateRange,
  type AlertsListState,
} from '../alertFilters';

// The bug this guards against only shows east of UTC: in IST, local midnight
// is 18:30 UTC the day before.
beforeAll(() => {
  vi.stubEnv('TZ', 'Asia/Kolkata');
});
afterAll(() => {
  vi.unstubAllEnvs();
});

const NOW = new Date('2026-10-19T04:30:45.123Z'); // 10:00:45 IST

describe('date ranges, in local time', () => {
  it('defaults to the last 7 days, counted back from now (to the minute)', () => {
    expect(DEFAULT_FILTERS.range).toBe('7d');
    expect(resolveDateRange(DEFAULT_FILTERS, NOW)).toEqual({ since: '2026-10-12T04:30:00.000Z' });
    expect(resolveDateRange({ ...DEFAULT_FILTERS, range: '30d' }, NOW).since).toBe('2026-09-19T04:30:00.000Z');
  });

  it('"today" starts at local midnight (18:30 UTC the day before, in IST)', () => {
    expect(resolveDateRange({ ...DEFAULT_FILTERS, range: 'today' }, NOW)).toEqual({
      since: '2026-10-18T18:30:00.000Z',
    });
  });

  it('custom dates are whole local days, end inclusive', () => {
    expect(
      resolveDateRange({ range: 'custom', dateFrom: '2026-10-01', dateTo: '2026-10-02' }, NOW)
    ).toEqual({ since: '2026-09-30T18:30:00.000Z', until: '2026-10-02T18:29:59.999Z' });
    expect(resolveDateRange({ range: 'custom', dateFrom: 'junk', dateTo: null }, NOW)).toEqual({
      since: undefined,
      until: undefined,
    });
  });

  it('all time sends no bounds', () => {
    expect(resolveDateRange({ ...DEFAULT_FILTERS, range: 'all' }, NOW)).toEqual({});
  });
});

describe('filters -> query', () => {
  it('sends every filter to the backend, repeatable ones repeated', () => {
    const params = alertFiltersToParams(
      {
        ...DEFAULT_FILTERS,
        statuses: ['open', 'reviewed'],
        severities: ['critical', 'high'],
        area: 'REFORMER1',
        violationType: 'ppe_violation:missing_gloves',
        range: '30d',
      },
      3,
      10,
      NOW
    );
    expect(params).toMatchObject({
      status: ['open', 'reviewed'],
      severity: ['critical', 'high'],
      area: 'REFORMER1',
      type: 'ppe_violation',
      type_detail: 'missing_gloves',
      since: '2026-09-19T04:30:00.000Z',
      offset: 20,
      limit: 10,
    });
    const qs = new URLSearchParams(buildQueryString(params).slice(1));
    expect(qs.getAll('status')).toEqual(['open', 'reviewed']);
    expect(qs.getAll('severity')).toEqual(['critical', 'high']);
    expect(qs.get('offset')).toBe('20');
  });
});

describe('URL state', () => {
  const state = (over: Partial<AlertsListState> = {}): AlertsListState => ({
    filters: DEFAULT_FILTERS,
    page: 1,
    pageSize: 10,
    expanded: null,
    ...over,
  });

  it('defaults make an empty query string, and parse back to defaults', () => {
    expect(listStateToSearch(state()).toString()).toBe('');
    expect(listStateFromSearch(new URLSearchParams(''))).toEqual(state());
  });

  it('round-trips every filter, the page, page size and expanded incident', () => {
    const full = state({
      filters: {
        statuses: ['open', 'reviewed'],
        range: 'custom',
        dateFrom: '2026-10-01',
        dateTo: '2026-10-05',
        cameraId: 'cam-1',
        violationType: 'ppe_violation:missing_gloves',
        severities: ['critical'],
        area: 'MW02 PF COLUMN',
      },
      page: 3,
      pageSize: 25,
      expanded: 'cam-1:missing_gloves:v1',
    });
    const search = listStateToSearch(full);
    expect(search.toString()).toBe(
      'status=open&status=reviewed&range=custom&from=2026-10-01&to=2026-10-05&camera=cam-1' +
        '&type=ppe_violation%3Amissing_gloves&severity=critical&area=MW02+PF+COLUMN&page=3&per_page=25' +
        '&open=cam-1%3Amissing_gloves%3Av1'
    );
    expect(listStateFromSearch(new URLSearchParams(search.toString()))).toEqual(full);
  });

  it('an empty status selection is "any", distinct from the default', () => {
    const none = state({ filters: { ...DEFAULT_FILTERS, statuses: [] } });
    expect(listStateToSearch(none).toString()).toBe('status=any');
    expect(listStateFromSearch(new URLSearchParams('status=any')).filters.statuses).toEqual([]);
  });

  it('ignores junk and uses the remembered page size when the URL has none', () => {
    const parsed = listStateFromSearch(
      new URLSearchParams('status=bogus&range=year&severity=urgent&page=-2&per_page=7'),
      25
    );
    expect(parsed.filters.statuses).toEqual([]); // a status param was given; none valid
    expect(parsed.filters.range).toBe('7d');
    expect(parsed.filters.severities).toEqual([]);
    expect(parsed.page).toBe(1);
    expect(parsed.pageSize).toBe(25);
    // ...and a URL that matches the remembered size doesn't repeat it
    expect(listStateToSearch(state({ pageSize: 25 }), 25).toString()).toBe('');
  });
});

describe('area options', () => {
  it('distinct manways, sorted naturally, blanks skipped', () => {
    expect(
      cameraAreas([
        { manway: 'REFORMER2' }, { manway: 'MW10 PF COLUMN' }, { manway: 'MW02 PF COLUMN' },
        { manway: 'REFORMER2' }, { manway: null }, { manway: '  ' },
      ])
    ).toEqual(['MW02 PF COLUMN', 'MW10 PF COLUMN', 'REFORMER2']);
  });
});
