import { Link } from 'react-router-dom';
import './CameraDetailSkeleton.css';

/**
 * Camera Detail Skeleton (F4 §7.4)
 *
 * Loading placeholder for camera detail view.
 */
export function CameraDetailSkeleton() {
  return (
    <div className="camera-detail-skeleton">
      {/* Back navigation */}
      <nav className="camera-detail-skeleton__nav">
        <Link to="/cameras" className="camera-detail-skeleton__back">
          &larr; Back to Cameras
        </Link>
      </nav>

      {/* Header skeleton */}
      <div className="camera-detail-skeleton__header">
        <div className="camera-detail-skeleton__title" />
        <div className="camera-detail-skeleton__badge" />
      </div>

      {/* Content */}
      <div className="camera-detail-skeleton__content">
        {/* Video section */}
        <div className="camera-detail-skeleton__video">
          <div className="camera-detail-skeleton__video-placeholder" />
          <div className="camera-detail-skeleton__status-bar" />
        </div>

        {/* Sidebar */}
        <div className="camera-detail-skeleton__sidebar">
          {/* Info card */}
          <div className="camera-detail-skeleton__card">
            <div className="camera-detail-skeleton__card-title" />
            <div className="camera-detail-skeleton__card-item" />
            <div className="camera-detail-skeleton__card-item" />
            <div className="camera-detail-skeleton__card-item" />
          </div>

          {/* Violations card */}
          <div className="camera-detail-skeleton__card">
            <div className="camera-detail-skeleton__card-title" />
            <div className="camera-detail-skeleton__list-item" />
            <div className="camera-detail-skeleton__list-item" />
            <div className="camera-detail-skeleton__list-item" />
          </div>
        </div>
      </div>
    </div>
  );
}
