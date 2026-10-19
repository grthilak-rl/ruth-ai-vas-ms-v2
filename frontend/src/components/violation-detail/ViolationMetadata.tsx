import type { Violation } from '../../state/api';
import type { ConfidenceCategory } from '../../state';
import { SeverityBadge } from '../alerts/SeverityBadge';
import { cameraHeadline, cameraNumber } from '../../utils/violationDisplay';
import { dismissReasonLabel } from '../../utils/dismissReasons';
import {
  LABEL_SEPARATOR,
  violationDetailLabel,
  violationTypeLabel,
} from '../../utils/violationLabels';
import './ViolationMetadata.css';

interface ViolationMetadataProps {
  violation: Violation;
  confidenceCategory: ConfidenceCategory;
  confidenceLabel: string;
}

/**
 * Format relative time
 */
function formatRelativeTime(isoTimestamp: string): string {
  const date = new Date(isoTimestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMinutes = Math.floor(diffMs / 60000);

  if (diffMinutes < 1) return 'Just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;

  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

/**
 * Get status display label (F6 §3.3)
 */
function getStatusLabel(status: Violation['status']): string {
  switch (status) {
    case 'open':
      return 'Unreviewed';
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
 * Violation Metadata Component (F4 §6.1)
 *
 * Displays violation metadata in the detail sidebar.
 *
 * Per F4 wireframe:
 * - Type
 * - Camera
 * - Confidence (category only)
 * - Status
 * - Detected time
 *
 * HARD RULES:
 * - F3: No model version shown to operators
 * - F3: No raw confidence numbers
 * - F3: No event IDs or technical identifiers
 */
export function ViolationMetadata({
  violation,
  confidenceCategory,
  confidenceLabel,
}: ViolationMetadataProps) {
  const relativeTime = formatRelativeTime(violation.timestamp);
  const statusLabel = getStatusLabel(violation.status);
  // "PPE Violation · Missing gloves", or just "Fall Detected".
  const typeLabel = violationTypeLabel(violation);
  const detailLabel = violationDetailLabel(violation);

  return (
    <div className="violation-metadata">
      <h2 className="violation-metadata__title">Metadata</h2>

      <dl className="violation-metadata__list">
        <div className="violation-metadata__item">
          <dt className="violation-metadata__label">Type</dt>
          <dd className="violation-metadata__value">
            {/* Each half wraps as a unit, so a narrow column breaks at the
                separator rather than mid-label ("Missing / gloves"). */}
            <span className="violation-metadata__nowrap">{typeLabel}</span>
            {detailLabel && (
              <>
                {LABEL_SEPARATOR}
                <span className="violation-metadata__nowrap">{detailLabel}</span>
              </>
            )}
          </dd>
        </div>

        <div className="violation-metadata__item">
          <dt className="violation-metadata__label">Camera</dt>
          <dd className="violation-metadata__value">
            <span className="violation-metadata__nowrap">{cameraHeadline(violation)}</span>{' '}
            <span className="violation-metadata__nowrap">#{cameraNumber(violation)}</span>
          </dd>
        </div>

        <div className="violation-metadata__item">
          <dt className="violation-metadata__label">Severity</dt>
          <dd className="violation-metadata__value">
            <SeverityBadge severity={violation.severity} />
          </dd>
        </div>

        <div className="violation-metadata__item">
          <dt className="violation-metadata__label">Confidence</dt>
          <dd className={`violation-metadata__value violation-metadata__confidence--${confidenceCategory}`}>
            {confidenceLabel}
          </dd>
        </div>

        <div className="violation-metadata__item">
          <dt className="violation-metadata__label">Status</dt>
          <dd className={`violation-metadata__value violation-metadata__status--${violation.status}`}>
            <span className="violation-metadata__status-dot">●</span>
            {statusLabel}
          </dd>
        </div>

        {violation.status === 'dismissed' && violation.dismiss_reason && (
          <div className="violation-metadata__item">
            <dt className="violation-metadata__label">Dismissed as</dt>
            <dd className="violation-metadata__value">
              {dismissReasonLabel(violation.dismiss_reason)}
              {violation.resolution_notes && (
                <span className="violation-metadata__note">“{violation.resolution_notes}”</span>
              )}
            </dd>
          </div>
        )}

        <div className="violation-metadata__item">
          <dt className="violation-metadata__label">Detected</dt>
          <dd className="violation-metadata__value">{relativeTime}</dd>
        </div>

        {violation.reviewed_by && (
          <div className="violation-metadata__item">
            <dt className="violation-metadata__label">Reviewed by</dt>
            <dd className="violation-metadata__value violation-metadata__value--secondary">
              {violation.reviewed_by}
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}
