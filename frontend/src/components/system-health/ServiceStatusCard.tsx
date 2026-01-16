import './ServiceStatusCard.css';

export type ServiceHealthStatus = 'healthy' | 'degraded' | 'offline';

interface ServiceStatusCardProps {
  /** Service name (e.g., "Ruth Backend", "AI Runtime") */
  serviceName: string;
  /** Current health status */
  status: ServiceHealthStatus;
  /** Human-readable description of current state */
  description?: string;
  /** Last updated timestamp (displayed as relative) */
  lastUpdated?: string;
}

/**
 * Service Status Card (F4 §9.1)
 *
 * Shows health status for a single service.
 *
 * Per E8 Constraints:
 * - No pod, container, or process names
 * - No raw metrics (CPU, memory, latency numbers)
 * - Human-readable descriptions only
 */
export function ServiceStatusCard({
  serviceName,
  status,
  description,
  lastUpdated,
}: ServiceStatusCardProps) {
  const statusLabel = getStatusLabel(status);
  const statusIcon = getStatusIcon(status);

  return (
    <div className={`service-status-card service-status-card--${status}`}>
      <div className="service-status-card__header">
        <h3 className="service-status-card__name">{serviceName}</h3>
      </div>
      <div className="service-status-card__content">
        <span className={`service-status-card__indicator service-status-card__indicator--${status}`}>
          <span className="service-status-card__icon">{statusIcon}</span>
          <span className="service-status-card__label">{statusLabel}</span>
        </span>
        {description && (
          <p className="service-status-card__description">{description}</p>
        )}
      </div>
      {lastUpdated && (
        <div className="service-status-card__footer">
          <span className="service-status-card__updated">
            Updated {formatRelativeTime(lastUpdated)}
          </span>
        </div>
      )}
    </div>
  );
}

function getStatusLabel(status: ServiceHealthStatus): string {
  switch (status) {
    case 'healthy':
      return 'Healthy';
    case 'degraded':
      return 'Degraded';
    case 'offline':
      return 'Offline';
  }
}

function getStatusIcon(status: ServiceHealthStatus): string {
  switch (status) {
    case 'healthy':
      return '●';
    case 'degraded':
      return '◐';
    case 'offline':
      return '○';
  }
}

function formatRelativeTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSecs = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffSecs / 60);
    const diffHours = Math.floor(diffMins / 60);

    if (diffSecs < 60) {
      return `${diffSecs}s ago`;
    } else if (diffMins < 60) {
      return `${diffMins}m ago`;
    } else if (diffHours < 24) {
      return `${diffHours}h ago`;
    }
    return date.toLocaleDateString();
  } catch {
    return 'recently';
  }
}
