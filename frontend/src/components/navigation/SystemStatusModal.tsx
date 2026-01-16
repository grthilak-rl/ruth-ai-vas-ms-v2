import { useEffect, useCallback, useRef } from 'react';
import type { GlobalStatus } from '../../state';
import './SystemStatusModal.css';

/**
 * Status messages per F3 Flow 4
 *
 * HARD RULES:
 * - MUST show human-readable summary only
 * - MUST NOT expose component names, service names, or error codes
 * - MUST NOT block user workflow (non-blocking modal)
 */
const STATUS_MESSAGES: Record<GlobalStatus, { title: string; message: string }> = {
  healthy: {
    title: 'All Systems OK',
    message: 'All systems are operating normally.',
  },
  degraded: {
    title: 'System Degraded',
    message:
      'AI detection may be slower or less accurate. Video monitoring continues normally.',
  },
  offline: {
    title: 'System Offline',
    message:
      'System status is currently unavailable. Some features may not work.',
  },
};

interface SystemStatusModalProps {
  isOpen: boolean;
  onClose: () => void;
  status: GlobalStatus;
}

/**
 * System Status Modal (F3 Flow 4)
 *
 * Non-blocking modal displaying human-readable system status.
 *
 * Rules:
 * - Operator/Supervisor only (Admin navigates to health page)
 * - Shows friendly message, no technical details
 * - Dismissible via close button, backdrop click, or Escape key
 * - MUST NOT block user workflow
 */
export function SystemStatusModal({
  isOpen,
  onClose,
  status,
}: SystemStatusModalProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const config = STATUS_MESSAGES[status];

  // Handle Escape key
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    },
    [onClose]
  );

  // Focus management and keyboard handling
  useEffect(() => {
    if (isOpen) {
      // Focus the close button when modal opens
      closeButtonRef.current?.focus();

      // Add escape key listener
      document.addEventListener('keydown', handleKeyDown);

      return () => {
        document.removeEventListener('keydown', handleKeyDown);
      };
    }
  }, [isOpen, handleKeyDown]);

  // Handle backdrop click
  const handleBackdropClick = useCallback(
    (event: React.MouseEvent) => {
      if (event.target === event.currentTarget) {
        onClose();
      }
    },
    [onClose]
  );

  if (!isOpen) {
    return null;
  }

  return (
    <div
      className="status-modal-backdrop"
      onClick={handleBackdropClick}
      role="presentation"
    >
      <div
        ref={modalRef}
        className={`status-modal status-modal--${status}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="status-modal-title"
        aria-describedby="status-modal-description"
      >
        <div className="status-modal__header">
          <h2 id="status-modal-title" className="status-modal__title">
            {config.title}
          </h2>
          <button
            ref={closeButtonRef}
            type="button"
            className="status-modal__close"
            onClick={onClose}
            aria-label="Close status modal"
          >
            ×
          </button>
        </div>

        <div className="status-modal__content">
          <p id="status-modal-description" className="status-modal__message">
            {config.message}
          </p>
        </div>

        <div className="status-modal__footer">
          <button
            type="button"
            className="status-modal__dismiss"
            onClick={onClose}
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}
