import { Link } from 'react-router-dom';
import type { Device, Violation, CameraStatus, DetectionStatus } from '../../state';
import { CameraStatusBadge } from './CameraStatusBadge';
import { DetectionStatusBadge } from './DetectionStatusBadge';
import { LiveVideoPlayer } from '../video';
import { CameraViolationsList } from './CameraViolationsList';
import './CameraDetailView.css';

interface CameraDetailViewProps {
  device: Device;
  cameraStatus: CameraStatus;
  detectionStatus: DetectionStatus;
  /** Recent violations for this camera (read-only) */
  violations?: Violation[];
  /** Whether violations are loading */
  violationsLoading?: boolean;
}

/**
 * Camera Detail View (F4 §7.3)
 *
 * Live camera monitoring with detection status and recent violations.
 *
 * Per E7 Task Spec:
 * - Live video that continues working when AI is paused
 * - Clear detection status messaging (non-alarming)
 * - Recent violations (read-only, non-blocking)
 * - Split functionality: video and AI are independent
 *
 * HARD RULES:
 * - F3: Video continues even when AI is paused/unavailable
 * - No stream IDs or internal identifiers
 * - No inference metrics (FPS, latency)
 * - No model names or versions to operators
 * - No auto-stop due to AI failure
 */
export function CameraDetailView({
  device,
  cameraStatus,
  detectionStatus,
  violations = [],
  violationsLoading = false,
}: CameraDetailViewProps) {
  const isVideoAvailable = cameraStatus === 'live';

  return (
    <div className="camera-detail">
      {/* Back navigation */}
      <nav className="camera-detail__nav">
        <Link to="/cameras" className="camera-detail__back">
          &larr; Back to Cameras
        </Link>
      </nav>

      {/* Header */}
      <header className="camera-detail__header">
        <h1 className="camera-detail__title">{device.name}</h1>
        <CameraStatusBadge status={cameraStatus} />
      </header>

      {/* Main content */}
      <div className="camera-detail__content">
        {/* Video section */}
        <section className="camera-detail__video-section">
          <LiveVideoPlayer
            deviceId={device.id}
            deviceName={device.name}
            isAvailable={isVideoAvailable}
            streamId={device.streaming.stream_id}
            isDetectionActive={detectionStatus === 'active'}
          />

          {/* Detection status message (below video) */}
          <div className="camera-detail__detection-status">
            <DetectionStatusBadge status={detectionStatus} />
            <DetectionStatusMessage status={detectionStatus} />
          </div>
        </section>

        {/* Sidebar */}
        <aside className="camera-detail__sidebar">
          {/* Camera info */}
          <div className="camera-detail__info-card">
            <h3 className="camera-detail__info-title">Camera Info</h3>
            <dl className="camera-detail__info-list">
              <div className="camera-detail__info-item">
                <dt>Name</dt>
                <dd>{device.name}</dd>
              </div>
              <div className="camera-detail__info-item">
                <dt>Status</dt>
                <dd>
                  <CameraStatusBadge status={cameraStatus} />
                </dd>
              </div>
              <div className="camera-detail__info-item">
                <dt>Detection</dt>
                <dd>
                  <DetectionStatusBadge status={detectionStatus} />
                </dd>
              </div>
            </dl>
          </div>

          {/* Recent violations */}
          <div className="camera-detail__violations-card">
            <div className="camera-detail__violations-header">
              <h3 className="camera-detail__violations-title">
                Today's Violations
              </h3>
              <Link
                to={`/alerts?camera=${device.id}`}
                className="camera-detail__violations-link"
              >
                View All
              </Link>
            </div>
            <CameraViolationsList
              violations={violations}
              isLoading={violationsLoading}
            />
          </div>
        </aside>
      </div>
    </div>
  );
}

/**
 * Detection status message component
 *
 * Per E7 constraints:
 * - Informational only
 * - Non-alarming
 * - Never blame the operator
 */
function DetectionStatusMessage({ status }: { status: DetectionStatus }) {
  switch (status) {
    case 'active':
      return (
        <p className="camera-detail__detection-message">
          AI detection is monitoring this camera.
        </p>
      );
    case 'paused':
      return (
        <p className="camera-detail__detection-message camera-detail__detection-message--warning">
          Detection is temporarily paused. Video monitoring continues normally.
        </p>
      );
    case 'disabled':
      return (
        <p className="camera-detail__detection-message camera-detail__detection-message--muted">
          Detection is disabled for this camera.
        </p>
      );
  }
}
