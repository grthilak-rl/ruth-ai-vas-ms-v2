import './SystemHealthSkeleton.css';

/**
 * System Health Skeleton (F4 §9.2)
 *
 * Loading placeholder for System Health screen.
 */
export function SystemHealthSkeleton() {
  return (
    <div className="system-health-skeleton">
      {/* Header */}
      <div className="system-health-skeleton__header">
        <div className="system-health-skeleton__title" />
        <div className="system-health-skeleton__status" />
      </div>

      {/* Service Cards */}
      <div className="system-health-skeleton__section">
        <div className="system-health-skeleton__section-title" />
        <div className="system-health-skeleton__services">
          <div className="system-health-skeleton__card" />
          <div className="system-health-skeleton__card" />
          <div className="system-health-skeleton__card" />
        </div>
      </div>

      {/* Model Cards */}
      <div className="system-health-skeleton__section">
        <div className="system-health-skeleton__section-title" />
        <div className="system-health-skeleton__models">
          <div className="system-health-skeleton__model" />
          <div className="system-health-skeleton__model" />
        </div>
      </div>

      {/* Audit Events */}
      <div className="system-health-skeleton__section">
        <div className="system-health-skeleton__section-title" />
        <div className="system-health-skeleton__events">
          <div className="system-health-skeleton__event" />
          <div className="system-health-skeleton__event" />
          <div className="system-health-skeleton__event" />
        </div>
      </div>
    </div>
  );
}
