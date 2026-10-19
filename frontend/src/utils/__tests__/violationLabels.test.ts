/**
 * Violation labels: API labels first, built-in fallback, title-case last;
 * the Alerts type filter's encoding and grouping; and the new response
 * fields never blacking out the list.
 */

import { describe, expect, it } from 'vitest';
import {
  buildTypeFilterEntries,
  detailLabelFor,
  encodeTypeFilter,
  familyLabel,
  titleCase,
  typeFilterToParams,
  violationCombinedLabel,
  violationDetailLabel,
  violationShortLabel,
  violationTypeLabel,
} from '../violationLabels';
import { isViolation, isViolationTypesResponse } from '../../state/api/validators';

/** Shaped like a real list row from the new backend. */
const GLOVES = {
  id: '3f6c9a7e-0000-4000-8000-000000000001',
  type: 'ppe_violation',
  type_detail: 'missing_gloves',
  type_label: 'PPE Violation',
  detail_label: 'Missing gloves',
  camera_id: '3f6c9a7e-0000-4000-8000-0000000000aa',
  camera_name: 'Dock 2',
  status: 'open',
  confidence: 0.81,
  timestamp: '2026-10-19T10:00:00Z',
  reviewed_by: null,
  reviewed_at: null,
  created_at: '2026-10-19T10:00:00Z',
  updated_at: '2026-10-19T10:00:00Z',
};

const FALL = {
  ...GLOVES,
  type: 'fall_detected',
  type_detail: null,
  type_label: 'Fall Detected',
  detail_label: null,
};

describe('labels from the API', () => {
  it('combines family and specific type for the detail page', () => {
    expect(violationCombinedLabel(GLOVES)).toBe('PPE Violation · Missing gloves');
    expect(violationTypeLabel(GLOVES)).toBe('PPE Violation');
    expect(violationDetailLabel(GLOVES)).toBe('Missing gloves');
    expect(violationShortLabel(GLOVES)).toBe('Missing gloves');
  });

  it('shows the family alone when there is no specific type', () => {
    expect(violationCombinedLabel(FALL)).toBe('Fall Detected');
    expect(violationDetailLabel(FALL)).toBeNull();
    expect(violationShortLabel(FALL)).toBe('Fall Detected');
  });

  it('prefers the API label (a manifest display_name) over the built-in', () => {
    expect(violationDetailLabel({ ...GLOVES, detail_label: 'Gloves off' })).toBe('Gloves off');
  });
});

describe('fallback for an older backend (no label fields)', () => {
  const bare = (type: string, type_detail?: string | null) => ({ type, type_detail });

  it('uses the built-in labels, standardised on "Fall Detected"', () => {
    expect(violationTypeLabel(bare('fall_detected'))).toBe('Fall Detected');
    expect(violationCombinedLabel(bare('ppe_violation', 'missing_hardhat'))).toBe(
      'PPE Violation · Missing hard hat'
    );
    expect(violationCombinedLabel(bare('zone_intrusion', 'tank_critical_high'))).toBe(
      'Zone Intrusion · Tank level critically high'
    );
    expect(violationCombinedLabel(bare('fall_detected', 'possible_fall'))).toBe(
      'Fall Detected · Possible fall'
    );
    expect(familyLabel('unauthorized_access')).toBe('Unauthorized Entry');
  });

  it('title-cases unknown values only', () => {
    expect(titleCase('missing_safety_boots')).toBe('Missing Safety Boots');
    expect(detailLabelFor('missing_safety_boots')).toBe('Missing Safety Boots');
    expect(familyLabel('fire_detected')).toBe('Fire Detected');
    expect(detailLabelFor(null)).toBeNull();
    expect(detailLabelFor('  ')).toBeNull();
  });

  it('ignores label fields of the wrong type rather than rendering them', () => {
    const odd = { type: 'ppe_violation', type_detail: 7, detail_label: 5 } as unknown as {
      type: string;
    };
    expect(violationCombinedLabel(odd)).toBe('PPE Violation');
  });
});

describe('type filter encoding', () => {
  it('round-trips family, specific type and "no specific type"', () => {
    expect(typeFilterToParams('')).toEqual({});
    expect(typeFilterToParams(encodeTypeFilter('ppe_violation'))).toEqual({ type: 'ppe_violation' });
    expect(typeFilterToParams(encodeTypeFilter('ppe_violation', 'missing_gloves'))).toEqual({
      type: 'ppe_violation',
      type_detail: 'missing_gloves',
    });
    expect(typeFilterToParams(encodeTypeFilter('ppe_violation', null))).toEqual({
      type: 'ppe_violation',
      type_detail: 'none',
    });
  });
});

describe('type filter options', () => {
  const items = [
    {
      type: 'ppe_violation',
      label: 'PPE Violation',
      count: 1600,
      details: [
        { type_detail: 'missing_vest', label: 'Missing safety vest', count: 1053 },
        { type_detail: 'missing_gloves', label: 'Missing gloves', count: 404 },
        { type_detail: null, label: 'PPE Violation', count: 3 },
      ],
    },
    { type: 'fall_detected', label: 'Fall Detected', count: 2, details: [] },
  ];

  it('groups specific types under their family, with an "All" entry first', () => {
    expect(buildTypeFilterEntries(items)).toEqual([
      {
        kind: 'group',
        label: 'PPE Violation',
        options: [
          { value: 'ppe_violation', label: 'All PPE Violation' },
          { value: 'ppe_violation:missing_vest', label: 'Missing safety vest' },
          { value: 'ppe_violation:missing_gloves', label: 'Missing gloves' },
          { value: 'ppe_violation:none', label: 'PPE Violation' },
        ],
      },
      { kind: 'option', option: { value: 'fall_detected', label: 'Fall Detected' } },
    ]);
  });

  it('keeps a selected type that is no longer offered, so the select stays honest', () => {
    const entries = buildTypeFilterEntries(items, 'zone_intrusion:tank_critical_low');
    expect(entries.at(-1)).toEqual({
      kind: 'option',
      option: {
        value: 'zone_intrusion:tank_critical_low',
        label: 'Zone Intrusion · Tank level critically low',
      },
    });
    expect(buildTypeFilterEntries(items, 'ppe_violation:missing_gloves')).toHaveLength(2);
  });
});

describe('validators', () => {
  it('accepts rows with and without the new label fields', () => {
    expect(isViolation(GLOVES)).toBe(true);
    expect(isViolation(FALL)).toBe(true);
    const legacy: Record<string, unknown> = { ...GLOVES };
    delete legacy.type_detail;
    delete legacy.type_label;
    delete legacy.detail_label;
    expect(isViolation(legacy)).toBe(true);
  });

  it('validates the types response', () => {
    expect(
      isViolationTypesResponse({
        items: [
          {
            type: 'ppe_violation',
            label: 'PPE Violation',
            count: 2,
            details: [{ type_detail: null, label: 'PPE Violation', count: 2 }],
          },
        ],
      })
    ).toBe(true);
    expect(isViolationTypesResponse({ items: [{ type: 'x', label: 'X', count: '2', details: [] }] })).toBe(
      false
    );
    expect(isViolationTypesResponse({})).toBe(false);
  });
});
