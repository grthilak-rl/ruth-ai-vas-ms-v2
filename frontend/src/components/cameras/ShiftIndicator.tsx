import { memo, useEffect, useState } from 'react';
import { useCurrentShiftQuery } from '../../state/hooks/useShiftQuery';
import {
  formatShiftWindow,
  formatTimeRemaining,
  millisUntilShiftEnd,
} from '../../state/api/shifts.api';
import './ShiftIndicator.css';

/**
 * ShiftIndicator Component
 *
 * Toolbar readout of the shift currently running: its name, its window,
 * and how much of it is left ("Night shift · 19:00–07:00 · 3h 20m left").
 *
 * Render isolation
 * ----------------
 * The countdown has to advance every minute, but the toolbar and the
 * camera grid beside it must not re-render when it does — a grid of live
 * WebRTC tiles is expensive to reconcile, and nothing in it depends on
 * the clock.
 *
 * So the ticking state lives in ShiftTimeRemaining and nowhere else.
 * React re-renders from the component whose state changed downwards, so a
 * tick reconciles exactly one memoised leaf that renders a single string.
 * The parent holds only server data, which changes twice a day.
 *
 * The tick is per minute, not per second, because the display has minute
 * resolution — a per-second timer would produce 59 renders that paint
 * identical text.
 */

interface ShiftTimeRemainingProps {
  /** ISO 8601 shift end. A primitive, so memo() compares by value. */
  endsAt: string;
}

/**
 * The only part of the toolbar that re-renders on the minute.
 *
 * Aligned to the wall-clock minute boundary rather than to mount time, so
 * the readout changes when the minute changes instead of drifting up to
 * 59 seconds behind it.
 */
const ShiftTimeRemaining = memo(function ShiftTimeRemaining({
  endsAt,
}: ShiftTimeRemainingProps) {
  const [remainingMs, setRemainingMs] = useState(() => millisUntilShiftEnd(endsAt));

  useEffect(() => {
    setRemainingMs(millisUntilShiftEnd(endsAt));

    let intervalId: number | undefined;

    const msToNextMinute = 60_000 - (Date.now() % 60_000);
    const alignId = window.setTimeout(() => {
      setRemainingMs(millisUntilShiftEnd(endsAt));
      intervalId = window.setInterval(() => {
        setRemainingMs(millisUntilShiftEnd(endsAt));
      }, 60_000);
    }, msToNextMinute);

    return () => {
      window.clearTimeout(alignId);
      if (intervalId !== undefined) window.clearInterval(intervalId);
    };
  }, [endsAt]);

  return (
    <span className="shift-indicator__remaining">{formatTimeRemaining(remainingMs)}</span>
  );
});

export function ShiftIndicator() {
  const { data: shift, isLoading, isError } = useCurrentShiftQuery();

  // The toolbar should not grow a broken-looking slot when the shift
  // service is unreachable; the cameras are the point of this screen.
  if (isLoading || isError || !shift) {
    return null;
  }

  const isContinuous = shift.mode === 'continuous';

  return (
    <div
      className="shift-indicator"
      title={
        isContinuous
          ? 'No shifts configured — counting violations for the current day'
          : `Shift times are ${shift.timezone}`
      }
    >
      <span className="shift-indicator__name">
        {isContinuous ? 'Continuous' : shift.name}
      </span>
      <span className="shift-indicator__separator">·</span>
      <span className="shift-indicator__window">{formatShiftWindow(shift)}</span>
      <span className="shift-indicator__separator">·</span>
      <ShiftTimeRemaining endsAt={shift.end} />
    </div>
  );
}
