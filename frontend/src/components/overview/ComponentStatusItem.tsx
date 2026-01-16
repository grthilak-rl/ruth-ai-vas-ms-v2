import type { ComponentHealthStatus } from '../../state';
import './ComponentStatusItem.css';

interface ComponentStatusItemProps {
  /** Component display name */
  name: string;
  /** Component health status */
  status: ComponentHealthStatus;
  /** Latency in milliseconds */
  latencyMs?: number | null;
  /** Additional detail text (e.g., "3 connections") */
  detail?: string | null;
  /** Whether data is loading */
  isLoading?: boolean;
}

/**
 * Status indicator configuration
 *
 * | Status    | Visual | ARIA Label        |
 * |-----------|--------|-------------------|
 * | healthy   | 🟢     | Healthy           |
 * | degraded  | 🟡     | Degraded          |
 * | unhealthy | 🔴     | Unhealthy         |
 * | loading   | ⚫     | Checking...       |
 */
const STATUS_CONFIG: Record<ComponentHealthStatus | 'loading', { symbol: string; className: string; label: string }> = {
  healthy: { symbol: '●', className: 'component-status__dot--healthy', label: 'Healthy' },
  degraded: { symbol: '●', className: 'component-status__dot--degraded', label: 'Degraded' },
  unhealthy: { symbol: '●', className: 'component-status__dot--unhealthy', label: 'Unhealthy' },
  loading: { symbol: '○', className: 'component-status__dot--loading', label: 'Checking...' },
};

/**
 * Individual Component Status Item
 *
 * Displays health status for a single system component (Database, Redis, etc.)
 *
 * Per F4 wireframes:
 * - Shows status indicator (colored dot)
 * - Shows component name
 * - Shows latency when available
 * - Shows additional detail when available
 */
export function ComponentStatusItem({
  name,
  status,
  latencyMs,
  detail,
  isLoading = false,
}: ComponentStatusItemProps) {
  const config = STATUS_CONFIG[isLoading ? 'loading' : status];

  return (
    <div
      className="component-status"
      role="listitem"
      aria-label={`${name}: ${config.label}`}
    >
      <span
        className={`component-status__dot ${config.className}`}
        aria-hidden="true"
      >
        {config.symbol}
      </span>
      <div className="component-status__info">
        <span className="component-status__name">{name}</span>
        {!isLoading && latencyMs != null && (
          <span className="component-status__latency">{latencyMs}ms</span>
        )}
        {isLoading && (
          <span className="component-status__latency component-status__latency--loading">
            ...
          </span>
        )}
        {!isLoading && detail && (
          <span className="component-status__detail">{detail}</span>
        )}
      </div>
    </div>
  );
}
