import { describe, expect, it } from 'vitest';
import { buildQueryString } from '../../../state/api/violations.api';
import { alertFiltersToParams, cameraAreas } from '../alertFilters';
import { DEFAULT_FILTERS } from '../AlertsFilterSidebar';

describe('sidebar filters -> query', () => {
  it('sends every filter to the backend, statuses and severities repeated', () => {
    const params = alertFiltersToParams(
      {
        ...DEFAULT_FILTERS,
        statuses: ['open', 'reviewed'],
        severities: ['critical', 'high'],
        area: 'REFORMER1',
        violationType: 'ppe_violation:missing_gloves',
        dateFrom: '2026-10-19',
      },
      3,
      10
    );
    expect(params).toMatchObject({
      status: ['open', 'reviewed'],
      severity: ['critical', 'high'],
      area: 'REFORMER1',
      type: 'ppe_violation',
      type_detail: 'missing_gloves',
      since: '2026-10-19T00:00:00Z',
      offset: 20,
      limit: 10,
    });
    const qs = new URLSearchParams(buildQueryString(params).slice(1));
    expect(qs.getAll('status')).toEqual(['open', 'reviewed']);
    expect(qs.getAll('severity')).toEqual(['critical', 'high']);
    expect(qs.get('area')).toBe('REFORMER1');
    expect(qs.get('offset')).toBe('20');
  });

  it('omits empty filters', () => {
    const params = alertFiltersToParams({ ...DEFAULT_FILTERS, statuses: [] }, 1, 10);
    expect(params.status).toBeUndefined();
    expect(params.severity).toBeUndefined();
    expect(params.area).toBeUndefined();
    expect(buildQueryString(params)).toBe('?offset=0&limit=10');
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
