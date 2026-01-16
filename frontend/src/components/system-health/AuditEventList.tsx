import './AuditEventList.css';

export type AuditEventType =
  | 'model_rollback'
  | 'model_upgrade'
  | 'model_health_change'
  | 'system_degradation'
  | 'system_recovery'
  | 'system_startup';

export interface AuditEvent {
  id: string;
  type: AuditEventType;
  timestamp: string;
  message: string;
  details?: string;
}

interface AuditEventListProps {
  events: AuditEvent[];
  isLoading?: boolean;
  maxItems?: number;
}

/**
 * Audit Event List (F4 §9.1)
 *
 * Read-only list of system and model events.
 *
 * Per E8 Constraints:
 * - No raw logs
 * - No stack traces
 * - Human-readable descriptions only
 *
 * Shows:
 * - Model rollbacks
 * - Model health state transitions
 * - System-wide degradation/recovery events
 */
export function AuditEventList({
  events,
  isLoading = false,
  maxItems = 10,
}: AuditEventListProps) {
  if (isLoading) {
    return (
      <div className="audit-event-list__loading">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="audit-event-list__skeleton" />
        ))}
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="audit-event-list__empty">
        <p>No recent system events</p>
      </div>
    );
  }

  const displayEvents = events.slice(0, maxItems);

  return (
    <ul className="audit-event-list">
      {displayEvents.map((event) => (
        <AuditEventItem key={event.id} event={event} />
      ))}
    </ul>
  );
}

function AuditEventItem({ event }: { event: AuditEvent }) {
  const icon = getEventIcon(event.type);
  const iconClass = getEventIconClass(event.type);

  return (
    <li className="audit-event-list__item">
      <span className={`audit-event-list__icon ${iconClass}`} aria-hidden="true">
        {icon}
      </span>
      <div className="audit-event-list__content">
        <span className="audit-event-list__message">{event.message}</span>
        {event.details && (
          <span className="audit-event-list__details">{event.details}</span>
        )}
      </div>
      <span className="audit-event-list__time">{formatEventTime(event.timestamp)}</span>
    </li>
  );
}

function getEventIcon(type: AuditEventType): string {
  switch (type) {
    case 'model_rollback':
      return '↩';
    case 'model_upgrade':
      return '↑';
    case 'model_health_change':
      return '◐';
    case 'system_degradation':
      return '⚠';
    case 'system_recovery':
      return '✓';
    case 'system_startup':
      return '●';
    default:
      return '•';
  }
}

function getEventIconClass(type: AuditEventType): string {
  switch (type) {
    case 'model_rollback':
    case 'system_degradation':
    case 'model_health_change':
      return 'audit-event-list__icon--warning';
    case 'system_recovery':
    case 'model_upgrade':
      return 'audit-event-list__icon--success';
    default:
      return 'audit-event-list__icon--neutral';
  }
}

function formatEventTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return 'Unknown';
  }
}
