import { useEffect } from 'react';
import './Toast.css';

export type ToastType = 'success' | 'error' | 'info';

interface ToastProps {
  message: string;
  type: ToastType;
  isVisible: boolean;
  onDismiss: () => void;
  /** Auto-dismiss after N milliseconds (default: 5000). Set to 0 to disable. */
  autoDismissMs?: number;
}

/**
 * Toast Notification Component (F4 §6.8)
 *
 * Brief feedback messages for operator actions.
 *
 * Per F4:
 * - Auto-dismiss after 5 seconds
 * - Manual dismiss available
 *
 * Per F5 §A1:
 * - Toast: "Violation dismissed" after dismissal
 */
export function Toast({
  message,
  type,
  isVisible,
  onDismiss,
  autoDismissMs = 5000,
}: ToastProps) {
  // Auto-dismiss
  useEffect(() => {
    if (isVisible && autoDismissMs > 0) {
      const timer = setTimeout(onDismiss, autoDismissMs);
      return () => clearTimeout(timer);
    }
  }, [isVisible, autoDismissMs, onDismiss]);

  if (!isVisible) {
    return null;
  }

  return (
    <div
      className={`toast toast--${type}`}
      role={type === 'error' ? 'alert' : 'status'}
      aria-live={type === 'error' ? 'assertive' : 'polite'}
    >
      <span className="toast__message">{message}</span>
      <button
        type="button"
        className="toast__dismiss"
        onClick={onDismiss}
        aria-label="Dismiss notification"
      >
        ×
      </button>
    </div>
  );
}
