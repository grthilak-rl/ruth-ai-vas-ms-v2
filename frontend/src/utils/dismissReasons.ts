/**
 * Dismiss reasons (mirrors app/models/dismiss_reasons.py).
 *
 * False alarms copy the inferred frame to the labelling set for the AI
 * engineer; "pipework/object" and "PPE actually worn" also get an empty
 * YOLO label (a true background image for that model).
 */

import type { DismissReason } from '../state/api';

export interface DismissReasonOption {
  value: DismissReason;
  label: string;
  hint: string;
}

export const FALSE_ALARM_OPTIONS: DismissReasonOption[] = [
  { value: 'object', label: 'Pipework / object', hint: 'Something in the scene was taken for the target' },
  { value: 'wrong_person', label: 'Wrong person', hint: 'A real person, but not the one the rule is about' },
  { value: 'ppe_worn', label: 'PPE actually worn', hint: 'The PPE flagged as missing is there' },
  { value: 'other_false_alarm', label: 'Other false alarm', hint: 'Describe it in the note' },
];

export const NOT_FALSE_ALARM_OPTIONS: DismissReasonOption[] = [
  { value: 'duplicate', label: 'Duplicate / already handled', hint: 'Real, but dealt with elsewhere' },
];

const LABELS = Object.fromEntries(
  [...FALSE_ALARM_OPTIONS, ...NOT_FALSE_ALARM_OPTIONS].map((o) => [o.value, o.label])
) as Record<DismissReason, string>;

export function dismissReasonLabel(reason: string | null | undefined): string | null {
  return reason ? (LABELS[reason as DismissReason] ?? reason) : null;
}

export function isFalseAlarm(reason: DismissReason | null | undefined): boolean {
  return !!reason && FALSE_ALARM_OPTIONS.some((o) => o.value === reason);
}

export function noteRequired(reason: DismissReason | null | undefined): boolean {
  return reason === 'other_false_alarm';
}
