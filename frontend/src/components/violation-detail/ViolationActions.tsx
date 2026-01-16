import './ViolationActions.css';

interface ViolationActionsProps {
  canAcknowledge: boolean;
  canDismiss: boolean;
  canEscalate: boolean;
  canResolve: boolean;
  onAcknowledge: () => void;
  onDismiss: () => void;
  onEscalate: () => void;
  onResolve: () => void;
  pendingAction: 'acknowledge' | 'dismiss' | 'escalate' | 'resolve' | null;
}

/**
 * Violation Actions Component (F3 Flow 3, F4 §6)
 *
 * Action buttons for violation management.
 *
 * Per F3 Flow 3:
 * - Acknowledge: No confirmation required
 * - Dismiss: Requires confirmation (handled by parent)
 * - Escalate: Operator only
 * - Resolve: Supervisor/Admin only
 *
 * Per E6 constraints:
 * - Actions MUST remain available even if evidence is missing
 * - One failing action must not block others
 */
export function ViolationActions({
  canAcknowledge,
  canDismiss,
  canEscalate,
  canResolve,
  onAcknowledge,
  onDismiss,
  onEscalate,
  onResolve,
  pendingAction,
}: ViolationActionsProps) {
  const isPending = pendingAction !== null;

  return (
    <div className="violation-actions">
      <h2 className="violation-actions__title">Actions</h2>

      <div className="violation-actions__buttons">
        {canAcknowledge && (
          <button
            type="button"
            className="violation-actions__button violation-actions__button--acknowledge"
            onClick={onAcknowledge}
            disabled={isPending}
            aria-busy={pendingAction === 'acknowledge'}
          >
            {pendingAction === 'acknowledge' ? 'Saving...' : 'Mark as Reviewed'}
          </button>
        )}

        {canDismiss && (
          <button
            type="button"
            className="violation-actions__button violation-actions__button--dismiss"
            onClick={onDismiss}
            disabled={isPending}
            aria-busy={pendingAction === 'dismiss'}
          >
            {pendingAction === 'dismiss' ? 'Saving...' : 'Dismiss'}
          </button>
        )}

        {canEscalate && (
          <button
            type="button"
            className="violation-actions__button violation-actions__button--escalate"
            onClick={onEscalate}
            disabled={isPending}
            aria-busy={pendingAction === 'escalate'}
          >
            {pendingAction === 'escalate' ? 'Sending...' : 'Escalate'}
          </button>
        )}

        {canResolve && (
          <button
            type="button"
            className="violation-actions__button violation-actions__button--resolve"
            onClick={onResolve}
            disabled={isPending}
            aria-busy={pendingAction === 'resolve'}
          >
            {pendingAction === 'resolve' ? 'Saving...' : 'Resolve'}
          </button>
        )}

        {!canAcknowledge && !canDismiss && !canEscalate && !canResolve && (
          <p className="violation-actions__empty">No actions available</p>
        )}
      </div>
    </div>
  );
}
