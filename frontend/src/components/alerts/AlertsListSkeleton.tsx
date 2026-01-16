import './AlertsListSkeleton.css';

/**
 * Alerts List Skeleton Component
 *
 * Loading state placeholder per F4.
 * Shows skeleton cards while data loads.
 *
 * Per E5 constraints:
 * - No full-page blocking spinner
 * - Skeleton placeholders
 */
export function AlertsListSkeleton() {
  // Show 3 skeleton cards
  return (
    <div className="alerts-list-skeleton" aria-busy="true" aria-label="Loading alerts">
      <div className="alerts-list-skeleton__card">
        <div className="alerts-list-skeleton__thumbnail" />
        <div className="alerts-list-skeleton__content">
          <div className="alerts-list-skeleton__header">
            <div className="alerts-list-skeleton__title" />
            <div className="alerts-list-skeleton__badges">
              <div className="alerts-list-skeleton__badge" />
              <div className="alerts-list-skeleton__badge" />
            </div>
          </div>
          <div className="alerts-list-skeleton__meta" />
          <div className="alerts-list-skeleton__actions">
            <div className="alerts-list-skeleton__action" />
            <div className="alerts-list-skeleton__action" />
            <div className="alerts-list-skeleton__action" />
          </div>
        </div>
      </div>

      <div className="alerts-list-skeleton__card">
        <div className="alerts-list-skeleton__thumbnail" />
        <div className="alerts-list-skeleton__content">
          <div className="alerts-list-skeleton__header">
            <div className="alerts-list-skeleton__title" />
            <div className="alerts-list-skeleton__badges">
              <div className="alerts-list-skeleton__badge" />
              <div className="alerts-list-skeleton__badge" />
            </div>
          </div>
          <div className="alerts-list-skeleton__meta" />
          <div className="alerts-list-skeleton__actions">
            <div className="alerts-list-skeleton__action" />
            <div className="alerts-list-skeleton__action" />
            <div className="alerts-list-skeleton__action" />
          </div>
        </div>
      </div>

      <div className="alerts-list-skeleton__card">
        <div className="alerts-list-skeleton__thumbnail" />
        <div className="alerts-list-skeleton__content">
          <div className="alerts-list-skeleton__header">
            <div className="alerts-list-skeleton__title" />
            <div className="alerts-list-skeleton__badges">
              <div className="alerts-list-skeleton__badge" />
              <div className="alerts-list-skeleton__badge" />
            </div>
          </div>
          <div className="alerts-list-skeleton__meta" />
          <div className="alerts-list-skeleton__actions">
            <div className="alerts-list-skeleton__action" />
            <div className="alerts-list-skeleton__action" />
            <div className="alerts-list-skeleton__action" />
          </div>
        </div>
      </div>
    </div>
  );
}
