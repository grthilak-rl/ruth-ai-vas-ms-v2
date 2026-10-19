/**
 * Violation type labels — the one place the UI turns types into words.
 *
 * A violation has a family (`type`: fall_detected, ppe_violation, ...) and,
 * usually, a specific type (`type_detail`: missing_gloves, ...). The backend
 * resolves both labels (manifest display_name > built-in > title-case) and
 * sends them as `type_label` / `detail_label`; this module prefers those and
 * only falls back to its own copy of the built-ins when they are missing,
 * e.g. against an older backend.
 *
 * Replaces four per-component maps that disagreed ("Fall Detection" on a
 * card, "Fall Detected" on the detail page, raw values elsewhere).
 */

import type { Violation } from '../state/api';

/** Separator between family and specific label: "PPE Violation · Missing gloves". */
export const LABEL_SEPARATOR = ' · ';

/** `type_detail` filter value for "no specific type" (mirrors the backend). */
export const NO_TYPE_DETAIL = 'none';

const FAMILY_LABELS: Record<string, string> = {
  fall_detected: 'Fall Detected',
  ppe_violation: 'PPE Violation',
  zone_intrusion: 'Zone Intrusion',
  zone_exit: 'Zone Exit',
  // Legacy value still present in older data on the overview.
  unauthorized_access: 'Unauthorized Entry',
};

/** Mirror of the backend's BUILTIN_DETAIL_LABELS, used only as a fallback. */
const BUILTIN_DETAIL_LABELS: Record<string, string> = {
  missing_hardhat: 'Missing hard hat',
  missing_vest: 'Missing safety vest',
  missing_goggles: 'Missing goggles',
  missing_mask: 'Missing mask',
  missing_gloves: 'Missing gloves',
  missing_harness: 'Missing safety harness',
  possible_fall: 'Possible fall',
  tank_overflow_warning: 'Tank overflow warning',
  tank_critical_high: 'Tank level critically high',
  tank_critical_low: 'Tank level critically low',
};

type LabelSource = Pick<Violation, 'type'> &
  Partial<Pick<Violation, 'type_detail' | 'type_label' | 'detail_label'>>;

function nonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

/** `missing_safety_boots` -> `Missing Safety Boots`. */
export function titleCase(value: string): string {
  return value
    .replace(/-/g, '_')
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/** Label for a family value on its own (filter groups, legacy rows). */
export function familyLabel(type: string): string {
  return FAMILY_LABELS[type] ?? titleCase(type);
}

/** Label for a specific type on its own, or null for none. */
export function detailLabelFor(typeDetail: string | null | undefined): string | null {
  const detail = nonEmptyString(typeDetail)?.toLowerCase();
  if (!detail) return null;
  return BUILTIN_DETAIL_LABELS[detail] ?? titleCase(detail);
}

/** "PPE Violation" — the family. */
export function violationTypeLabel(violation: LabelSource): string {
  return nonEmptyString(violation.type_label) ?? familyLabel(violation.type);
}

/** "Missing gloves" — the specific type, or null when there is none. */
export function violationDetailLabel(violation: LabelSource): string | null {
  // An explicit null from the backend means "no specific type": don't
  // second-guess it from type_detail.
  if (violation.detail_label === null && violation.type_label !== undefined) return null;
  return nonEmptyString(violation.detail_label) ?? detailLabelFor(violation.type_detail);
}

/** "PPE Violation · Missing gloves", or just "Fall Detected". */
export function violationCombinedLabel(violation: LabelSource): string {
  const family = violationTypeLabel(violation);
  const detail = violationDetailLabel(violation);
  return detail ? `${family}${LABEL_SEPARATOR}${detail}` : family;
}

/** The most specific label alone — for compact rows and card headlines. */
export function violationShortLabel(violation: LabelSource): string {
  return violationDetailLabel(violation) ?? violationTypeLabel(violation);
}

// ============================================================================
// Type filter
// ============================================================================
// The Alerts type filter is one <select>; each option's value encodes the
// family and, optionally, the specific type:
//   ''                               all types
//   'ppe_violation'                  the whole family
//   'ppe_violation:missing_gloves'   one specific type
//   'ppe_violation:none'             the family's violations with no specific type

export function encodeTypeFilter(type: string, typeDetail?: string | null): string {
  if (typeDetail === undefined) return type;
  return `${type}:${typeDetail ?? NO_TYPE_DETAIL}`;
}

/** Filter value -> violations API query params. */
export function typeFilterToParams(value: string): { type?: string; type_detail?: string } {
  if (!value) return {};
  const separator = value.indexOf(':');
  if (separator < 0) return { type: value };
  const type = value.slice(0, separator);
  const typeDetail = value.slice(separator + 1);
  return typeDetail ? { type, type_detail: typeDetail } : { type };
}

export interface TypeFilterOption {
  value: string;
  label: string;
}

/** A top-level entry: a family on its own, or a family with its specific types. */
export type TypeFilterEntry =
  | { kind: 'option'; option: TypeFilterOption }
  | { kind: 'group'; label: string; options: TypeFilterOption[] };

/**
 * GET /api/v1/violations/types -> <select> entries, grouped by family.
 *
 * A family with specific types becomes an <optgroup> that starts with
 * "All <family>"; one without becomes a plain option. If the current value
 * is no longer offered (a type that stopped occurring), it is kept as its
 * own option so the select never silently shows the wrong selection.
 */
export function buildTypeFilterEntries(
  items: Array<{
    type: string;
    label: string;
    details: Array<{ type_detail: string | null; label: string }>;
  }>,
  currentValue = ''
): TypeFilterEntry[] {
  const entries: TypeFilterEntry[] = items.map((family) =>
    family.details.length === 0
      ? { kind: 'option', option: { value: family.type, label: family.label } }
      : {
          kind: 'group',
          label: family.label,
          options: [
            { value: family.type, label: `All ${family.label}` },
            ...family.details.map((detail) => ({
              value: encodeTypeFilter(family.type, detail.type_detail),
              label: detail.label,
            })),
          ],
        }
  );

  const offered = entries.some((entry) =>
    entry.kind === 'option'
      ? entry.option.value === currentValue
      : entry.options.some((option) => option.value === currentValue)
  );
  if (currentValue && !offered) {
    const { type = '', type_detail } = typeFilterToParams(currentValue);
    const label =
      type_detail && type_detail !== NO_TYPE_DETAIL
        ? `${familyLabel(type)}${LABEL_SEPARATOR}${detailLabelFor(type_detail)}`
        : familyLabel(type);
    entries.push({ kind: 'option', option: { value: currentValue, label } });
  }
  return entries;
}
