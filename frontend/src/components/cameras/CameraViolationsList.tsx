import { Link } from 'react-router-dom';
import type { Violation } from '../../state';
import { getConfidenceCategory, getConfidenceDisplay } from '../../state';
import './CameraViolationsList.css';

interface CameraViolationsListProps {
  violations: Violation[];
  isLoading?: boolean;
}

/**
 * Camera Violations List (F4 §7.3)
 *
 * Read-only list of recent violations for a camera.
 *
 * Per E7 Task Spec:
 * - Read-only list or summary
 * - Non-blocking
 * - May be empty
 * - Handle missing or partial evidence gracefully
 *
 * HARD RULES:
 * - No raw confidence numbers
 * - No technical IDs
 */
export function CameraViolationsList({
  violations,
  isLoading = false,
}: CameraViolationsListProps) {
  if (isLoading) {
    return (
      <div className="camera-violations-list__loading">
        <div className="camera-violations-list__skeleton" />
        <div className="camera-violations-list__skeleton" />
        <div className="camera-violations-list__skeleton" />
      </div>
    );
  }

  if (violations.length === 0) {
    return (
      <div className="camera-violations-list__empty">
        <p>No violations today</p>
      </div>
    );
  }

  return (
    <ul className="camera-violations-list">
      {violations.slice(0, 5).map((violation) => (
        <ViolationItem key={violation.id} violation={violation} />
      ))}
    </ul>
  );
}

function ViolationItem({ violation }: { violation: Violation }) {
  const confidenceCategory = getConfidenceCategory(violation.confidence);
  const confidenceLabel = getConfidenceDisplay(violation.confidence);
  const time = formatTime(violation.timestamp);

  return (
    <li className="camera-violations-list__item">
      <Link
        to={`/alerts/${violation.id}`}
        className="camera-violations-list__link"
      >
        <span
          className={`camera-violations-list__dot camera-violations-list__dot--${confidenceCategory}`}
          aria-hidden="true"
        />
        <span className="camera-violations-list__type">
          {formatViolationType(violation.type)}
        </span>
        <span
          className={`camera-violations-list__confidence camera-violations-list__confidence--${confidenceCategory}`}
        >
          {confidenceLabel}
        </span>
        <span className="camera-violations-list__time">{time}</span>
        <span className="camera-violations-list__arrow" aria-hidden="true">
          &rarr;
        </span>
      </Link>
    </li>
  );
}

/**
 * Format violation type for display
 */
function formatViolationType(type: string): string {
  // Convert snake_case to Title Case
  return type
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * Format timestamp to time only (HH:MM)
 */
function formatTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  } catch {
    return '--:--';
  }
}
