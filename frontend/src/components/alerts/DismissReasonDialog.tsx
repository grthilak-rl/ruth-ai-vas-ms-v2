import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { DismissReason } from '../../state/api';
import {
  FALSE_ALARM_OPTIONS,
  NOT_FALSE_ALARM_OPTIONS,
  isFalseAlarm,
  noteRequired,
  type DismissReasonOption,
} from '../../utils/dismissReasons';
import './DismissConfirmationDialog.css';
import './DismissReasonDialog.css';

interface DismissReasonDialogProps {
  isOpen: boolean;
  /** How many violations will be dismissed */
  count: number;
  /** What is being dismissed, e.g. "Missing gloves on REFORMER2 · OUT, 10:02 – 10:31 AM." */
  context?: string;
  isPending?: boolean;
  onConfirm: (reason: DismissReason, note: string | undefined) => void;
  onCancel: () => void;
}

/**
 * Dismiss with a reason.
 *
 * Every dismissal says why: false alarms (and which kind) are exported to
 * the labelling set so the model can be retrained on its mistakes; a
 * duplicate is not. "Other false alarm" needs a note, since the reason
 * alone says nothing an engineer can act on.
 */
export function DismissReasonDialog({
  isOpen,
  count,
  context,
  isPending = false,
  onConfirm,
  onCancel,
}: DismissReasonDialogProps) {
  const [reason, setReason] = useState<DismissReason | null>(null);
  const [note, setNote] = useState('');
  const firstOptionRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const noteId = useId();

  // Fresh form each time it opens.
  const [openedFor, setOpenedFor] = useState(isOpen);
  if (isOpen !== openedFor) {
    setOpenedFor(isOpen);
    if (isOpen) {
      setReason(null);
      setNote('');
    }
  }

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isPending) onCancel();
    },
    [onCancel, isPending]
  );

  useEffect(() => {
    if (!isOpen) return;
    firstOptionRef.current?.focus();
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, handleKeyDown]);

  if (!isOpen) return null;

  const needsNote = noteRequired(reason);
  const canConfirm = !!reason && (!needsNote || note.trim().length > 0) && !isPending;
  const plural = count === 1 ? 'violation' : 'violations';

  const renderOption = (option: DismissReasonOption, index: number) => (
    <label key={option.value} className="dismiss-reason__option">
      <input
        ref={index === 0 ? firstOptionRef : undefined}
        type="radio"
        name="dismiss-reason"
        value={option.value}
        checked={reason === option.value}
        onChange={() => setReason(option.value)}
        disabled={isPending}
      />
      <span className="dismiss-reason__option-text">
        <span className="dismiss-reason__option-label">{option.label}</span>
        <span className="dismiss-reason__option-hint">{option.hint}</span>
      </span>
    </label>
  );

  return (
    <div
      className="dismiss-dialog-backdrop"
      role="presentation"
      onClick={(e) => e.target === e.currentTarget && !isPending && onCancel()}
    >
      <div className="dismiss-dialog dismiss-reason" role="alertdialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="dismiss-dialog__header">
          <h2 id={titleId} className="dismiss-dialog__title">
            Dismiss {count} {plural}
          </h2>
        </div>

        <div className="dismiss-dialog__content">
          {context && <p className="dismiss-dialog__message">{context}</p>}

          <fieldset className="dismiss-reason__group" disabled={isPending}>
            <legend className="dismiss-reason__legend">False alarm</legend>
            {FALSE_ALARM_OPTIONS.map(renderOption)}
          </fieldset>
          <fieldset className="dismiss-reason__group" disabled={isPending}>
            <legend className="dismiss-reason__legend">Not a false alarm</legend>
            {NOT_FALSE_ALARM_OPTIONS.map((o, i) => renderOption(o, i + FALSE_ALARM_OPTIONS.length))}
          </fieldset>

          <label htmlFor={noteId} className="dismiss-reason__note-label">
            Note{needsNote ? ' (required)' : ' (optional)'}
          </label>
          <textarea
            id={noteId}
            className="dismiss-reason__note"
            rows={2}
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={isPending}
            placeholder={needsNote ? 'What was mistaken for a violation?' : ''}
          />

          {isFalseAlarm(reason) && (
            <p className="dismiss-dialog__note">
              The inferred frame{count === 1 ? '' : 's'} will be copied to the labelling set for the AI
              engineer.
            </p>
          )}
        </div>

        <div className="dismiss-dialog__footer">
          <button
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
            onClick={() => reason && onConfirm(reason, note.trim() || undefined)}
            disabled={!canConfirm}
            aria-busy={isPending}
          >
            {isPending ? 'Dismissing...' : `Dismiss ${count}`}
          </button>
        </div>
      </div>
    </div>
  );
}
