import type { DetectionStatus } from '../../state';
import './DetectionStatusBadge.css';

interface DetectionStatusBadgeProps {
  status: DetectionStatus;
}

/**
 * Detection Status Badge (F4 §7, F6 §4.4)
 *
 * Shows AI detection status for a camera.
 *
 * Per E7 Task Spec:
 * - Detection Active: AI inference is running
 * - Detection Paused: AI is enabled but model unhealthy
 * - Detection Disabled: AI inference is turned off
 *
 * HARD RULES:
 * - No inference metrics (FPS, latency)
 * - No model names or versions
 * - Non-alarming messaging
 */
export function DetectionStatusBadge({ status }: DetectionStatusBadgeProps) {
  const label = getDetectionLabel(status);

  return (
    <span className={`detection-status-badge detection-status-badge--${status}`}>
      {label}
    </span>
  );
}

function getDetectionLabel(status: DetectionStatus): string {
  switch (status) {
    case 'active':
      return 'Detection Active';
    case 'paused':
      return 'Detection Paused';
    case 'disabled':
      return 'Detection Disabled';
  }
}
