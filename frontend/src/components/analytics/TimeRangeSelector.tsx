/**
 * Time Range Selector Component
 *
 * Per analytics-design.md §5.2.1
 * - Preset options: Last 24h, Last 7d, Last 30d, Custom
 * - Custom requires date picker
 * - Preset changes update immediately
 * - Custom requires Apply button
 */

import { useState } from 'react';
import type { TimeRangePreset } from '../../types/analytics';
import './TimeRangeSelector.css';

interface TimeRangeSelectorProps {
  /** Currently selected preset */
  selectedPreset: TimeRangePreset;
  /** Custom date range (if preset is 'custom') */
  customFrom?: Date;
  customTo?: Date;
  /** Callback when preset changes */
  onPresetChange: (preset: TimeRangePreset) => void;
  /** Callback when custom range is applied */
  onCustomRangeApply: (from: Date, to: Date) => void;
  /** Whether the component is disabled */
  disabled?: boolean;
}

export function TimeRangeSelector({
  selectedPreset,
  customFrom,
  customTo,
  onPresetChange,
  onCustomRangeApply,
  disabled = false,
}: TimeRangeSelectorProps) {
  const [localFrom, setLocalFrom] = useState<string>(
    customFrom ? formatDateForInput(customFrom) : ''
  );
  const [localTo, setLocalTo] = useState<string>(
    customTo ? formatDateForInput(customTo) : ''
  );

  const handlePresetClick = (preset: TimeRangePreset) => {
    if (disabled) return;
    onPresetChange(preset);
  };

  const handleApply = () => {
    if (disabled || !localFrom || !localTo) return;
    const from = new Date(localFrom);
    const to = new Date(localTo);
    onCustomRangeApply(from, to);
  };

  return (
    <div className="time-range-selector">
      <div className="time-range-selector__presets">
        <button
          type="button"
          className={`time-range-selector__preset ${selectedPreset === '24h' ? 'time-range-selector__preset--active' : ''}`}
          onClick={() => handlePresetClick('24h')}
          disabled={disabled}
        >
          Last 24h
        </button>
        <button
          type="button"
          className={`time-range-selector__preset ${selectedPreset === '7d' ? 'time-range-selector__preset--active' : ''}`}
          onClick={() => handlePresetClick('7d')}
          disabled={disabled}
        >
          Last 7d
        </button>
        <button
          type="button"
          className={`time-range-selector__preset ${selectedPreset === '30d' ? 'time-range-selector__preset--active' : ''}`}
          onClick={() => handlePresetClick('30d')}
          disabled={disabled}
        >
          Last 30d
        </button>
        <button
          type="button"
          className={`time-range-selector__preset ${selectedPreset === 'custom' ? 'time-range-selector__preset--active' : ''}`}
          onClick={() => handlePresetClick('custom')}
          disabled={disabled}
        >
          Custom
        </button>
      </div>

      {selectedPreset === 'custom' && (
        <div className="time-range-selector__custom">
          <label className="time-range-selector__label">
            From:
            <input
              type="datetime-local"
              className="time-range-selector__input"
              value={localFrom}
              onChange={(e) => setLocalFrom(e.target.value)}
              disabled={disabled}
            />
          </label>
          <label className="time-range-selector__label">
            To:
            <input
              type="datetime-local"
              className="time-range-selector__input"
              value={localTo}
              onChange={(e) => setLocalTo(e.target.value)}
              disabled={disabled}
            />
          </label>
          <button
            type="button"
            className="time-range-selector__apply"
            onClick={handleApply}
            disabled={disabled || !localFrom || !localTo}
          >
            Apply
          </button>
        </div>
      )}
    </div>
  );
}

function formatDateForInput(date: Date): string {
  // Format: YYYY-MM-DDTHH:mm
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}
