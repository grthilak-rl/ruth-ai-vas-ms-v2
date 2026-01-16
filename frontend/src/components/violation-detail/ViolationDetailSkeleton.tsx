import { Link } from 'react-router-dom';
import './ViolationDetailSkeleton.css';

/**
 * Violation Detail Skeleton (F4 §6.2)
 *
 * Loading state with skeleton placeholders.
 */
export function ViolationDetailSkeleton() {
  return (
    <div className="violation-detail-skeleton">
      {/* Back navigation */}
      <nav className="violation-detail-skeleton__nav">
        <Link to="/alerts" className="violation-detail-skeleton__back">
          ← Back to Alerts
        </Link>
      </nav>

      {/* Main content */}
      <div className="violation-detail-skeleton__content">
        {/* Evidence section */}
        <div className="violation-detail-skeleton__evidence">
          <div className="violation-detail-skeleton__image" />
        </div>

        {/* Metadata sidebar */}
        <div className="violation-detail-skeleton__sidebar">
          <div className="violation-detail-skeleton__metadata">
            <div className="violation-detail-skeleton__title" />
            <div className="violation-detail-skeleton__item" />
            <div className="violation-detail-skeleton__item" />
            <div className="violation-detail-skeleton__item" />
            <div className="violation-detail-skeleton__item" />
            <div className="violation-detail-skeleton__item" />
          </div>
        </div>
      </div>

      {/* Loading message */}
      <div className="violation-detail-skeleton__message">
        Loading violation details...
      </div>
    </div>
  );
}
