import { useState, useCallback, useMemo } from 'react';
import type { ViolationStatus, Device } from '../../state/api';
import './AlertsFilterSidebar.css';

/**
 * Filter state interface
 */
export interface AlertFilters {
  /** Selected statuses (empty = all) */
  statuses: ViolationStatus[];
  /** Start date for date range filter */
  dateFrom: string | null;
  /** End date for date range filter */
  dateTo: string | null;
  /** Selected camera ID (null = all) */
  cameraId: string | null;
}

/**
 * Default filter state
 */
export const DEFAULT_FILTERS: AlertFilters = {
  statuses: ['open'], // Default to open violations
  dateFrom: null,
  dateTo: null,
  cameraId: null,
};

/**
 * Date preset options
 */
type DatePreset = 'today' | 'last7days' | 'last30days' | 'custom';

interface AlertsFilterSidebarProps {
  /** Current filter state */
  filters: AlertFilters;
  /** Callback when filters change */
  onFiltersChange: (filters: AlertFilters) => void;
  /** Available cameras for dropdown */
  cameras: Device[];
  /** Whether cameras are loading */
  camerasLoading?: boolean;
}

/**
 * Status options for checkboxes
 */
const STATUS_OPTIONS: { value: ViolationStatus; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'reviewed', label: 'Reviewed' },
  { value: 'dismissed', label: 'Dismissed' },
  { value: 'resolved', label: 'Resolved' },
];

/**
 * Date preset options
 */
const DATE_PRESETS: { value: DatePreset; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: 'last7days', label: 'Last 7 Days' },
  { value: 'last30days', label: 'Last 30 Days' },
  { value: 'custom', label: 'Custom Range' },
];

/**
 * Get date range for preset
 */
function getDateRangeForPreset(preset: DatePreset): { from: string | null; to: string | null } {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  switch (preset) {
    case 'today':
      return {
        from: today.toISOString().split('T')[0],
        to: today.toISOString().split('T')[0],
      };
    case 'last7days': {
      const weekAgo = new Date(today);
      weekAgo.setDate(weekAgo.getDate() - 7);
      return {
        from: weekAgo.toISOString().split('T')[0],
        to: today.toISOString().split('T')[0],
      };
    }
    case 'last30days': {
      const monthAgo = new Date(today);
      monthAgo.setDate(monthAgo.getDate() - 30);
      return {
        from: monthAgo.toISOString().split('T')[0],
        to: today.toISOString().split('T')[0],
      };
    }
    case 'custom':
      return { from: null, to: null };
  }
}

/**
 * Determine active preset from date range
 */
function getActivePreset(dateFrom: string | null, dateTo: string | null): DatePreset | null {
  if (!dateFrom && !dateTo) return null;

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const todayStr = today.toISOString().split('T')[0];

  // Check if today
  if (dateFrom === todayStr && dateTo === todayStr) {
    return 'today';
  }

  // Check if last 7 days
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 7);
  if (dateFrom === weekAgo.toISOString().split('T')[0] && dateTo === todayStr) {
    return 'last7days';
  }

  // Check if last 30 days
  const monthAgo = new Date(today);
  monthAgo.setDate(monthAgo.getDate() - 30);
  if (dateFrom === monthAgo.toISOString().split('T')[0] && dateTo === todayStr) {
    return 'last30days';
  }

  // Custom range
  return 'custom';
}

/**
 * Alerts Filter Sidebar Component
 *
 * Provides filtering controls for the alerts list:
 * - Status checkboxes (Open, Reviewed, Dismissed, Resolved)
 * - Date range picker with presets (Today, Last 7 Days, Last 30 Days, Custom)
 * - Camera dropdown
 */
export function AlertsFilterSidebar({
  filters,
  onFiltersChange,
  cameras,
  camerasLoading = false,
}: AlertsFilterSidebarProps) {
  // Track whether custom date inputs are shown
  const [showCustomDates, setShowCustomDates] = useState(
    getActivePreset(filters.dateFrom, filters.dateTo) === 'custom'
  );

  // Determine active preset
  const activePreset = useMemo(
    () => getActivePreset(filters.dateFrom, filters.dateTo),
    [filters.dateFrom, filters.dateTo]
  );

  // Handle status toggle
  const handleStatusToggle = useCallback((status: ViolationStatus) => {
    const newStatuses = filters.statuses.includes(status)
      ? filters.statuses.filter(s => s !== status)
      : [...filters.statuses, status];

    onFiltersChange({
      ...filters,
      statuses: newStatuses,
    });
  }, [filters, onFiltersChange]);

  // Handle date preset selection
  const handlePresetSelect = useCallback((preset: DatePreset) => {
    if (preset === 'custom') {
      setShowCustomDates(true);
      return;
    }

    setShowCustomDates(false);
    const { from, to } = getDateRangeForPreset(preset);
    onFiltersChange({
      ...filters,
      dateFrom: from,
      dateTo: to,
    });
  }, [filters, onFiltersChange]);

  // Handle custom date change
  const handleDateFromChange = useCallback((value: string) => {
    onFiltersChange({
      ...filters,
      dateFrom: value || null,
    });
  }, [filters, onFiltersChange]);

  const handleDateToChange = useCallback((value: string) => {
    onFiltersChange({
      ...filters,
      dateTo: value || null,
    });
  }, [filters, onFiltersChange]);

  // Handle camera selection
  const handleCameraChange = useCallback((value: string) => {
    onFiltersChange({
      ...filters,
      cameraId: value || null,
    });
  }, [filters, onFiltersChange]);

  // Handle clear all filters
  const handleClearAll = useCallback(() => {
    setShowCustomDates(false);
    onFiltersChange(DEFAULT_FILTERS);
  }, [onFiltersChange]);

  // Check if any filters are active (different from default)
  const hasActiveFilters = useMemo(() => {
    return (
      filters.statuses.length !== 1 ||
      filters.statuses[0] !== 'open' ||
      filters.dateFrom !== null ||
      filters.dateTo !== null ||
      filters.cameraId !== null
    );
  }, [filters]);

  return (
    <aside className="alerts-filter-sidebar">
      <div className="alerts-filter-sidebar__header">
        <h2 className="alerts-filter-sidebar__title">Filters</h2>
        {hasActiveFilters && (
          <button
            type="button"
            className="alerts-filter-sidebar__clear"
            onClick={handleClearAll}
          >
            Clear All
          </button>
        )}
      </div>

      {/* Status Filter */}
      <section className="alerts-filter-sidebar__section">
        <h3 className="alerts-filter-sidebar__section-title">Status</h3>
        <div className="alerts-filter-sidebar__checkboxes">
          {STATUS_OPTIONS.map(({ value, label }) => (
            <label key={value} className="alerts-filter-sidebar__checkbox-label">
              <input
                type="checkbox"
                checked={filters.statuses.includes(value)}
                onChange={() => handleStatusToggle(value)}
                className="alerts-filter-sidebar__checkbox"
              />
              <span className="alerts-filter-sidebar__checkbox-text">{label}</span>
            </label>
          ))}
        </div>
      </section>

      {/* Date Range Filter */}
      <section className="alerts-filter-sidebar__section">
        <h3 className="alerts-filter-sidebar__section-title">Date Range</h3>
        <div className="alerts-filter-sidebar__presets">
          {DATE_PRESETS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              className={`alerts-filter-sidebar__preset ${
                (value === 'custom' && showCustomDates) ||
                (value !== 'custom' && activePreset === value)
                  ? 'alerts-filter-sidebar__preset--active'
                  : ''
              }`}
              onClick={() => handlePresetSelect(value)}
            >
              {label}
            </button>
          ))}
        </div>

        {showCustomDates && (
          <div className="alerts-filter-sidebar__date-inputs">
            <div className="alerts-filter-sidebar__date-field">
              <label htmlFor="date-from" className="alerts-filter-sidebar__date-label">
                From
              </label>
              <input
                type="date"
                id="date-from"
                value={filters.dateFrom || ''}
                onChange={(e) => handleDateFromChange(e.target.value)}
                className="alerts-filter-sidebar__date-input"
              />
            </div>
            <div className="alerts-filter-sidebar__date-field">
              <label htmlFor="date-to" className="alerts-filter-sidebar__date-label">
                To
              </label>
              <input
                type="date"
                id="date-to"
                value={filters.dateTo || ''}
                onChange={(e) => handleDateToChange(e.target.value)}
                className="alerts-filter-sidebar__date-input"
              />
            </div>
          </div>
        )}
      </section>

      {/* Camera Filter */}
      <section className="alerts-filter-sidebar__section">
        <h3 className="alerts-filter-sidebar__section-title">Camera</h3>
        <select
          value={filters.cameraId || ''}
          onChange={(e) => handleCameraChange(e.target.value)}
          className="alerts-filter-sidebar__select"
          disabled={camerasLoading}
        >
          <option value="">All Cameras</option>
          {cameras.map((camera) => (
            <option key={camera.id} value={camera.id}>
              {camera.name}
            </option>
          ))}
        </select>
        {camerasLoading && (
          <span className="alerts-filter-sidebar__loading">Loading cameras...</span>
        )}
      </section>
    </aside>
  );
}
