import type { CameraStatus } from '../../state';
import './CameraStatusBadge.css';

interface CameraStatusBadgeProps {
  status: CameraStatus;
}

/**
 * Camera Status Badge (F4 §7.1)
 *
 * Visual indicator for camera connection status.
 *
 * Per F6 §4.4:
 * - live: Green dot with "Live" label
 * - offline: Gray dot with "Offline" label
 * - disabled: Gray dot with "Disabled" label
 *
 * HARD RULES:
 * - No stream IDs or internal identifiers
 * - No technical error messages
 */
export function CameraStatusBadge({ status }: CameraStatusBadgeProps) {
  const label = getStatusLabel(status);
  const dotClass = `camera-status-badge__dot camera-status-badge__dot--${status}`;

  return (
    <span className={`camera-status-badge camera-status-badge--${status}`}>
      <span className={dotClass} aria-hidden="true" />
      <span className="camera-status-badge__label">{label}</span>
    </span>
  );
}

function getStatusLabel(status: CameraStatus): string {
  switch (status) {
    case 'live':
      return 'Live';
    case 'offline':
      return 'Offline';
    case 'disabled':
      return 'Disabled';
  }
}
