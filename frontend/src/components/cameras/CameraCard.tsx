import { Link } from 'react-router-dom';
import type { Device, CameraStatus, DetectionStatus } from '../../state';
import { CameraStatusBadge } from './CameraStatusBadge';
import { DetectionStatusBadge } from './DetectionStatusBadge';
import './CameraCard.css';

interface CameraCardProps {
  device: Device;
  cameraStatus: CameraStatus;
  detectionStatus: DetectionStatus;
  violationCount?: number;
}

/**
 * Camera Card Component (F4 §7.1)
 *
 * Grid card showing camera thumbnail, status, and detection state.
 *
 * Per F4 wireframe:
 * - Thumbnail placeholder (or live feed snapshot)
 * - Camera name (human-readable)
 * - Live/Offline indicator
 * - Detection status
 * - Violation count for today
 *
 * HARD RULES:
 * - No stream IDs or internal identifiers
 * - No inference metrics
 * - Click navigates to Camera Detail
 */
export function CameraCard({
  device,
  cameraStatus,
  detectionStatus,
  violationCount,
}: CameraCardProps) {
  const isOffline = cameraStatus === 'offline' || cameraStatus === 'disabled';

  return (
    <Link
      to={`/cameras/${device.id}`}
      className={`camera-card ${isOffline ? 'camera-card--offline' : ''}`}
    >
      {/* Thumbnail area */}
      <div className="camera-card__thumbnail">
        {isOffline ? (
          <div className="camera-card__offline-indicator">
            <span className="camera-card__offline-text">OFFLINE</span>
          </div>
        ) : (
          <div className="camera-card__live-placeholder">
            <span className="camera-card__live-icon" aria-hidden="true" />
          </div>
        )}
      </div>

      {/* Info section */}
      <div className="camera-card__info">
        <div className="camera-card__header">
          <h3 className="camera-card__name">{device.name}</h3>
          <CameraStatusBadge status={cameraStatus} />
        </div>

        <div className="camera-card__footer">
          <DetectionStatusBadge status={detectionStatus} />
          {violationCount !== undefined && (
            <span className="camera-card__violations">
              {violationCount} violation{violationCount !== 1 ? 's' : ''}
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
