import type { ViolationStatus } from '../../state/api';
import './StatusBadge.css';

interface StatusBadgeProps {
  status: ViolationStatus;
}

/**
 * Status Badge Labels (F6 §3.3)
 *
 * | Status   | Frontend Display |
 * |----------|------------------|
 * | open     | "New"            |
 * | reviewed | "Reviewed"       |
 * | dismissed| "Dismissed"      |
 * | resolved | "Resolved"       |
 */
function getStatusLabel(status: ViolationStatus): string {
  switch (status) {
    case 'open':
      return 'New';
    case 'reviewed':
      return 'Reviewed';
    case 'dismissed':
      return 'Dismissed';
    case 'resolved':
      return 'Resolved';
    default:
      return status;
  }
}

/**
 * Status Badge Component (F4/F6-aligned)
 *
 * Displays violation status: New, Reviewed, etc.
 *
 * Per F6 §3.3:
 * - open → "New" badge
 * - reviewed → "Reviewed" badge
 * - dismissed → visible with Dismissed status filter
 * - resolved → visible with Resolved status filter
 */
export function StatusBadge({ status }: StatusBadgeProps) {
  const label = getStatusLabel(status);

  return (
    <span
      className={`status-badge status-badge--${status}`}
      aria-label={`Status: ${label}`}
    >
      {label}
    </span>
  );
}
