import { useEffect, useRef, useState } from 'react';
import {
  useShiftScheduleQuery,
  useUpdateShiftSchedule,
} from '../../state/hooks/useShiftQuery';
import { ApiError } from '../../state/api';
import type { ShiftDefinition, ShiftMode } from '../../state/api/shifts.api';
import './ShiftConfigDropdown.css';

/**
 * ShiftConfigDropdown Component
 *
 * Site-global shift schedule editor, sitting next to the Camera Selector.
 *
 * Two modes:
 * - Continuous: one 24h window aligned to the local calendar day. The
 *   default, and a legitimate posture — a plant that monitors round the
 *   clock without dividing the day has not failed to configure anything.
 * - Shifts: N named windows with wall-clock start/end times. They must
 *   tile the day exactly; the backend rejects overlaps and gaps, and its
 *   complaint is shown inline.
 *
 * Validation is deliberately not duplicated here. The backend owns the
 * rule because the same schedule has to be authoritative for reports and
 * filters later, and a second implementation in the browser is a second
 * thing to keep correct.
 */

/** Offered in the timezone picker. The site runs on the first. */
const TIMEZONE_OPTIONS = [
  'Asia/Kolkata',
  'Asia/Dubai',
  'Asia/Singapore',
  'Europe/London',
  'America/New_York',
  'UTC',
];

const MIN_SHIFTS = 1;
const MAX_SHIFTS = 6;

/**
 * Evenly divide the day into `count` shifts starting at 07:00.
 *
 * Used when the operator changes the shift count: the result already
 * tiles the day, so they are editing a valid schedule rather than
 * assembling one from an invalid start.
 */
function buildEvenShifts(count: number, existing: ShiftDefinition[]): ShiftDefinition[] {
  const minutesEach = Math.floor(1440 / count);
  const startOfDay = 7 * 60;

  return Array.from({ length: count }, (_, index) => {
    const startMinute = (startOfDay + index * minutesEach) % 1440;
    // The last shift absorbs the remainder so the day stays covered when
    // 1440 does not divide evenly (e.g. 7 shifts).
    const endMinute =
      index === count - 1 ? startOfDay % 1440 : (startMinute + minutesEach) % 1440;

    const asHHMM = (m: number) =>
      `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;

    return {
      name: existing[index]?.name ?? `Shift ${index + 1}`,
      start: asHHMM(startMinute),
      end: asHHMM(endMinute),
    };
  });
}

export function ShiftConfigDropdown() {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const { data: schedule, isLoading } = useShiftScheduleQuery();
  const updateSchedule = useUpdateShiftSchedule();

  const [mode, setMode] = useState<ShiftMode>('continuous');
  const [timezone, setTimezone] = useState('Asia/Kolkata');
  const [shifts, setShifts] = useState<ShiftDefinition[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<string[]>([]);

  // Seed the form from the server whenever the panel opens, so an
  // abandoned edit never leaks into the next one.
  useEffect(() => {
    if (!isOpen || !schedule) return;

    setMode(schedule.mode);
    setTimezone(schedule.timezone);
    setShifts(
      schedule.shifts.length > 0 ? schedule.shifts : buildEvenShifts(2, [])
    );
    setErrorMessage(null);
    setConflicts([]);
  }, [isOpen, schedule]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  const handleShiftCountChange = (count: number) => {
    setShifts((prev) => buildEvenShifts(count, prev));
  };

  const handleShiftFieldChange = (
    index: number,
    field: keyof ShiftDefinition,
    value: string
  ) => {
    setShifts((prev) =>
      prev.map((shift, i) => (i === index ? { ...shift, [field]: value } : shift))
    );
  };

  const handleSave = async () => {
    setErrorMessage(null);
    setConflicts([]);

    try {
      await updateSchedule.mutateAsync({
        mode,
        timezone,
        shifts: mode === 'shifts' ? shifts : [],
      });
      setIsOpen(false);
    } catch (error) {
      // The backend rejects overlaps and gaps with the offending shift
      // names or uncovered ranges; show them rather than a generic failure.
      if (error instanceof ApiError) {
        setErrorMessage(error.message);
        const reported = error.details?.conflicts;
        setConflicts(Array.isArray(reported) ? (reported as string[]) : []);
      } else {
        setErrorMessage('Could not save the shift schedule.');
      }
    }
  };

  return (
    <div className="shift-config-dropdown" ref={dropdownRef}>
      <button
        type="button"
        className="shift-config-dropdown__trigger"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
        aria-haspopup="true"
        disabled={isLoading}
      >
        Shift Config ▼
      </button>

      {isOpen && (
        <div
          className="shift-config-dropdown__panel"
          role="dialog"
          aria-label="Configure shift schedule"
        >
          <div className="shift-config-dropdown__header">
            <h3 className="shift-config-dropdown__title">Shift Schedule</h3>
            <button
              type="button"
              className="shift-config-dropdown__close"
              onClick={() => setIsOpen(false)}
              aria-label="Close shift configuration"
            >
              ✕
            </button>
          </div>

          <div className="shift-config-dropdown__content">
            <p className="shift-config-dropdown__hint">
              Applies to everyone at this site. Camera cards count unreviewed
              violations from the shift running now.
            </p>

            <fieldset className="shift-config-dropdown__modes">
              <legend className="shift-config-dropdown__legend">Mode</legend>

              <label className="shift-config-dropdown__radio">
                <input
                  type="radio"
                  name="shift-mode"
                  checked={mode === 'continuous'}
                  onChange={() => setMode('continuous')}
                />
                <span>
                  Continuous
                  <span className="shift-config-dropdown__radio-note">
                    one 24h window, 00:00–23:59
                  </span>
                </span>
              </label>

              <label className="shift-config-dropdown__radio">
                <input
                  type="radio"
                  name="shift-mode"
                  checked={mode === 'shifts'}
                  onChange={() => setMode('shifts')}
                />
                <span>
                  Shifts
                  <span className="shift-config-dropdown__radio-note">
                    named windows that cover the day
                  </span>
                </span>
              </label>
            </fieldset>

            <label className="shift-config-dropdown__field">
              <span className="shift-config-dropdown__field-label">Timezone</span>
              <select
                className="shift-config-dropdown__select"
                value={timezone}
                onChange={(event) => setTimezone(event.target.value)}
              >
                {TIMEZONE_OPTIONS.map((tz) => (
                  <option key={tz} value={tz}>
                    {tz}
                  </option>
                ))}
              </select>
            </label>

            {mode === 'shifts' && (
              <>
                <label className="shift-config-dropdown__field">
                  <span className="shift-config-dropdown__field-label">
                    Number of shifts
                  </span>
                  <input
                    className="shift-config-dropdown__number"
                    type="number"
                    min={MIN_SHIFTS}
                    max={MAX_SHIFTS}
                    value={shifts.length}
                    onChange={(event) => {
                      const next = Number(event.target.value);
                      if (next >= MIN_SHIFTS && next <= MAX_SHIFTS) {
                        handleShiftCountChange(next);
                      }
                    }}
                  />
                </label>

                <div className="shift-config-dropdown__shifts">
                  {shifts.map((shift, index) => (
                    <div key={index} className="shift-config-dropdown__shift-row">
                      <input
                        className="shift-config-dropdown__shift-name"
                        type="text"
                        value={shift.name}
                        maxLength={64}
                        aria-label={`Shift ${index + 1} name`}
                        onChange={(event) =>
                          handleShiftFieldChange(index, 'name', event.target.value)
                        }
                      />
                      <input
                        className="shift-config-dropdown__shift-time"
                        type="time"
                        value={shift.start}
                        aria-label={`Shift ${index + 1} start`}
                        onChange={(event) =>
                          handleShiftFieldChange(index, 'start', event.target.value)
                        }
                      />
                      <span className="shift-config-dropdown__shift-dash">–</span>
                      <input
                        className="shift-config-dropdown__shift-time"
                        type="time"
                        value={shift.end}
                        aria-label={`Shift ${index + 1} end`}
                        onChange={(event) =>
                          handleShiftFieldChange(index, 'end', event.target.value)
                        }
                      />
                    </div>
                  ))}
                </div>

                <p className="shift-config-dropdown__hint">
                  Shifts may cross midnight (19:00–07:00). They must not overlap,
                  and together they must cover all 24 hours.
                </p>
              </>
            )}

            {errorMessage && (
              <div className="shift-config-dropdown__error" role="alert">
                <p className="shift-config-dropdown__error-message">{errorMessage}</p>
                {conflicts.length > 0 && (
                  <ul className="shift-config-dropdown__conflicts">
                    {conflicts.map((conflict) => (
                      <li key={conflict}>{conflict}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>

          <div className="shift-config-dropdown__footer">
            <button
              type="button"
              className="shift-config-dropdown__cancel"
              onClick={() => setIsOpen(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="shift-config-dropdown__save"
              onClick={handleSave}
              disabled={updateSchedule.isPending}
            >
              {updateSchedule.isPending ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
