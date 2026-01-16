import { useEffect, useRef, useCallback } from 'react';
import './DismissConfirmationDialog.css';

interface DismissConfirmationDialogProps {
  isOpen: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  isPending?: boolean;
}

/**
 * Dismiss Confirmation Dialog (F3 Flow 3, F4 §6.5)
 *
 * Non-blocking confirmation for dismissing violations.
 *
 * Per F3 Flow 3:
 * - Dismiss requires confirmation (unlike Acknowledge)
 * - Dialog is non-blocking and dismissible
 * - "Dismiss is a judgment call that affects analytics"
 *
 * Per F4 §6.5:
 * - Title: "DISMISS VIOLATION"
 * - Message: "Are you sure you want to dismiss this alert?"
 * - Reason selection (simplified to notes in this implementation)
 * - Note: "Dismissed violations can be found using the Dismissed status filter"
 * - Buttons: Cancel, Dismiss
 *
 * HARD RULES:
 * - MUST be non-blocking (can close via Escape, backdrop click)
 * - MUST NOT block other violations from being acted upon
 */
export function DismissConfirmationDialog({
  isOpen,
  onConfirm,
  onCancel,
  isPending = false,
}: DismissConfirmationDialogProps) {
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Handle Escape key
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isPending) {
        onCancel();
      }
    },
    [onCancel, isPending]
  );

  // Focus management
  useEffect(() => {
    if (isOpen) {
      cancelButtonRef.current?.focus();
      document.addEventListener('keydown', handleKeyDown);

      return () => {
        document.removeEventListener('keydown', handleKeyDown);
      };
    }
  }, [isOpen, handleKeyDown]);

  // Handle backdrop click
  const handleBackdropClick = useCallback(
    (event: React.MouseEvent) => {
      if (event.target === event.currentTarget && !isPending) {
        onCancel();
      }
    },
    [onCancel, isPending]
  );

  if (!isOpen) {
    return null;
  }

  return (
    <div
      className="dismiss-dialog-backdrop"
      onClick={handleBackdropClick}
      role="presentation"
    >
      <div
        ref={dialogRef}
        className="dismiss-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="dismiss-dialog-title"
        aria-describedby="dismiss-dialog-description"
      >
        <div className="dismiss-dialog__header">
          <h2 id="dismiss-dialog-title" className="dismiss-dialog__title">
            Dismiss Violation
          </h2>
        </div>

        <div className="dismiss-dialog__content">
          <p id="dismiss-dialog-description" className="dismiss-dialog__message">
            Are you sure you want to dismiss this alert?
          </p>
          <p className="dismiss-dialog__note">
            This marks the violation as a false positive. Dismissed violations
            can be found using the "Dismissed" status filter and are counted for analytics.
          </p>
        </div>

        <div className="dismiss-dialog__footer">
          <button
            ref={cancelButtonRef}
            type="button"
            className="dismiss-dialog__button dismiss-dialog__button--cancel"
            onClick={onCancel}
            disabled={isPending}
          >
            Cancel
          </button>
          <button
            type="button"
            className="dismiss-dialog__button dismiss-dialog__button--confirm"
            onClick={onConfirm}
            disabled={isPending}
            aria-busy={isPending}
          >
            {isPending ? 'Dismissing...' : 'Yes, Dismiss'}
          </button>
        </div>
      </div>
    </div>
  );
}
