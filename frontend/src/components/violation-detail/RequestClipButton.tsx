import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchClipAvailability,
  requestViolationClip,
  type ClipAvailability,
} from '../../state/api';
import type { EvidenceStatus } from '../../state/api';

/**
 * "Request clip" for a violation that has none.
 *
 * Most violations have no clip because the auto-clip cooldown skipped them:
 * a busy camera fires every few seconds and each clip costs VAS an encode,
 * so only the first in a 60 s window gets one. The footage is still there,
 * and the violation carries an exact timestamp, so a clip can be cut on
 * demand.
 *
 * Availability is a real check against the recordings rather than a fixed
 * window. Reach differs per camera — each started recording at a different
 * time — and shifts as disk is pruned, so a hardcoded "7 days" would be
 * wrong in both directions.
 */

/** Poll while the clip is being cut. */
const POLL_MS = 3000;
/**
 * Stop polling after this long. A clip that cannot be cut now marks itself
 * failed in VAS, but a ceiling means a stuck job shows as "taking longer
 * than expected" instead of spinning for the rest of the session.
 */
const POLL_CEILING_MS = 3 * 60 * 1000;

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, {
        day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
      });
}

interface Props {
  violationId: string;
  /** Current clip status; null means no clip was ever requested. */
  bookmarkStatus: EvidenceStatus | null | undefined;
  /** Called when the clip reaches a terminal state, to refresh the violation. */
  onChanged?: () => void;
}

export function RequestClipButton({ violationId, bookmarkStatus, onChanged }: Props) {
  const [availability, setAvailability] = useState<ClipAvailability | null>(null);
  const [requesting, setRequesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const startedAt = useRef<number | null>(null);

  const inProgress = bookmarkStatus === 'pending' || bookmarkStatus === 'processing';
  const failed = bookmarkStatus === 'failed';
  // Only ask about availability when there is a decision to make. A
  // violation that already has a clip needs no recording check.
  const needsCheck = bookmarkStatus === null || bookmarkStatus === undefined || failed;

  useEffect(() => {
    if (!needsCheck) return;
    let cancelled = false;
    fetchClipAvailability(violationId)
      .then((a: ClipAvailability) => !cancelled && setAvailability(a))
      .catch(() => !cancelled && setAvailability({
        available: false,
        reason: 'could not check the recording',
      }));
    return () => { cancelled = true; };
  }, [violationId, needsCheck]);

  // Poll while the clip is being cut, with a ceiling.
  useEffect(() => {
    if (!inProgress) {
      startedAt.current = null;
      setTimedOut(false);
      return;
    }
    if (startedAt.current === null) startedAt.current = Date.now();
    const timer = setInterval(() => {
      if (startedAt.current !== null && Date.now() - startedAt.current > POLL_CEILING_MS) {
        setTimedOut(true);
        clearInterval(timer);
        return;
      }
      onChanged?.();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [inProgress, onChanged]);

  const handleRequest = useCallback(async () => {
    setRequesting(true);
    setError(null);
    try {
      await requestViolationClip(violationId);
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not request the clip');
    } finally {
      setRequesting(false);
    }
  }, [violationId, onChanged]);

  // A clip exists and is playable — the viewer renders the player, not us.
  if (bookmarkStatus === 'ready') return null;

  if (inProgress) {
    return (
      <div className="request-clip request-clip--working">
        <span className="request-clip__spinner" aria-hidden="true" />
        <span>
          {timedOut ? 'Clip is taking longer than expected' : 'Preparing clip…'}
        </span>
      </div>
    );
  }

  const unavailable = availability !== null && !availability.available;
  const oldest = availability?.oldest_recording;

  return (
    <div className="request-clip">
      <button
        type="button"
        className="request-clip__button"
        onClick={handleRequest}
        disabled={requesting || unavailable || availability === null}
        title={
          unavailable
            ? oldest
              ? `Recording only goes back to ${formatWhen(oldest)}`
              : availability?.reason ?? 'No recording for this moment'
            : 'Cut a 10-second clip around this detection'
        }
      >
        {requesting ? 'Requesting…' : unavailable ? 'Recording no longer available' : 'Request clip'}
      </button>
      {failed && !unavailable && (
        <span className="request-clip__note">Last attempt failed — try again</span>
      )}
      {error && <span className="request-clip__error">{error}</span>}
    </div>
  );
}
