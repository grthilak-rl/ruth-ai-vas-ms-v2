import { useViolationsQuery } from '../../state';
import './AlertsBadge.css';

/**
 * Alerts Badge - Live Count (F4/F6-aligned)
 *
 * Displays count of open violations from /api/v1/violations.
 *
 * Rules (F6 §10.4):
 * - Shows count of open violations only
 * - Shows "—" if data unavailable (error or loading)
 * - 10s polling interval (via useViolationsQuery)
 * - Never shows 0 - badge hidden when no open violations
 *
 * HARD RULES:
 * - MUST NOT block navigation if badge fails
 * - MUST NOT display stale data without indication
 */
export function AlertsBadge() {
  // Query open violations only
  const { data, isError, isLoading } = useViolationsQuery({
    status: 'open',
    limit: 1, // We only need the total count, minimize payload
  });

  // Determine display value per F6 §10.4
  const getDisplayValue = (): string | null => {
    // If error or loading on initial, show "—"
    if (isError) {
      return '—';
    }

    // If loading initial data, show nothing (badge hidden)
    if (isLoading && !data) {
      return null;
    }

    // If we have data, show the count
    if (data) {
      const count = data.total;

      // Hide badge when no open violations
      if (count === 0) {
        return null;
      }

      // Format count: cap at 99+ for display
      if (count > 99) {
        return '99+';
      }

      return String(count);
    }

    return null;
  };

  const displayValue = getDisplayValue();

  // Don't render badge if no value to display
  if (displayValue === null) {
    return null;
  }

  // Determine badge variant for styling
  const isUnavailable = displayValue === '—';

  return (
    <span
      className={`alerts-badge ${isUnavailable ? 'alerts-badge--unavailable' : ''}`}
      aria-label={
        isUnavailable
          ? 'Alert count unavailable'
          : `${displayValue} open alerts`
      }
    >
      {displayValue}
    </span>
  );
}
