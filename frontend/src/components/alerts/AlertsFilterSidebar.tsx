import { useCallback, useMemo } from 'react';
import type { ViolationStatus, Device, ViolationTypeOption, Severity } from '../../state/api';
import { deviceDisplayName } from '../../state/api';
import { buildTypeFilterEntries } from '../../utils/violationLabels';
import { SEVERITY_LEVELS, severityLabel } from '../../utils/violationDisplay';
import { DEFAULT_FILTERS, cameraAreas, type AlertFilters, type DateRange } from './alertFilters';
import './AlertsFilterSidebar.css';

interface AlertsFilterSidebarProps {
  /** Current filter state */
  filters: AlertFilters;
  /** Callback when filters change */
  onFiltersChange: (filters: AlertFilters) => void;
  /** Available cameras for dropdown */
  cameras: Device[];
  /** Whether cameras are loading */
  camerasLoading?: boolean;
  /** Families and specific types that occur, for the type dropdown */
  typeOptions: ViolationTypeOption[];
  /** Whether type options are loading */
  typeOptionsLoading?: boolean;
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

const DATE_RANGES: { value: DateRange; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: '7d', label: 'Last 7 Days' },
  { value: '30d', label: 'Last 30 Days' },
  { value: 'all', label: 'All Time' },
  { value: 'custom', label: 'Custom Range' },
];

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
  typeOptions,
  typeOptionsLoading = false,
}: AlertsFilterSidebarProps) {
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

  // Handle date range selection. Custom keeps any dates already entered.
  const handleRangeSelect = useCallback((range: DateRange) => {
    onFiltersChange({
      ...filters,
      range,
      dateFrom: range === 'custom' ? filters.dateFrom : null,
      dateTo: range === 'custom' ? filters.dateTo : null,
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

  const handleSeverityToggle = useCallback((level: Severity) => {
    onFiltersChange({
      ...filters,
      severities: filters.severities.includes(level)
        ? filters.severities.filter((s) => s !== level)
        : [...filters.severities, level],
    });
  }, [filters, onFiltersChange]);

  const handleAreaChange = useCallback((value: string) => {
    onFiltersChange({ ...filters, area: value || null });
  }, [filters, onFiltersChange]);

  const areas = useMemo(() => cameraAreas(cameras), [cameras]);

  // Handle violation type selection
  const handleTypeChange = useCallback((value: string) => {
    onFiltersChange({
      ...filters,
      violationType: value,
    });
  }, [filters, onFiltersChange]);

  const typeEntries = useMemo(
    () => buildTypeFilterEntries(typeOptions, filters.violationType),
    [typeOptions, filters.violationType]
  );

  // Handle clear all filters
  const handleClearAll = useCallback(() => {
    onFiltersChange(DEFAULT_FILTERS);
  }, [onFiltersChange]);

  // Check if any filters are active (different from default)
  const hasActiveFilters = useMemo(() => {
    return (
      filters.statuses.length !== 1 ||
      filters.statuses[0] !== 'open' ||
      filters.range !== DEFAULT_FILTERS.range ||
      filters.cameraId !== null ||
      filters.violationType !== '' ||
      filters.severities.length > 0 ||
      filters.area !== null
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
          {DATE_RANGES.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              className={`alerts-filter-sidebar__preset ${
                filters.range === value ? 'alerts-filter-sidebar__preset--active' : ''
              }`}
              onClick={() => handleRangeSelect(value)}
              aria-pressed={filters.range === value}
            >
              {label}
            </button>
          ))}
        </div>

        {filters.range === 'custom' && (
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
              {deviceDisplayName(camera)}
            </option>
          ))}
        </select>
        {camerasLoading && (
          <span className="alerts-filter-sidebar__loading">Loading cameras...</span>
        )}
      </section>

      {/* Severity Filter — the rule's severity, not confidence */}
      <section className="alerts-filter-sidebar__section">
        <h3 className="alerts-filter-sidebar__section-title">Severity</h3>
        <div className="alerts-filter-sidebar__checkboxes">
          {SEVERITY_LEVELS.map((level) => (
            <label key={level} className="alerts-filter-sidebar__checkbox-label">
              <input
                type="checkbox"
                checked={filters.severities.includes(level)}
                onChange={() => handleSeverityToggle(level)}
                className="alerts-filter-sidebar__checkbox"
              />
              <span className="alerts-filter-sidebar__checkbox-text">{severityLabel(level)}</span>
            </label>
          ))}
        </div>
      </section>

      {/* Area Filter — the camera's manway */}
      <section className="alerts-filter-sidebar__section">
        <h3 className="alerts-filter-sidebar__section-title">Area</h3>
        <select
          value={filters.area ?? ''}
          onChange={(e) => handleAreaChange(e.target.value)}
          className="alerts-filter-sidebar__select"
          aria-label="Camera area"
          disabled={camerasLoading}
        >
          <option value="">All Areas</option>
          {areas.map((area) => (
            <option key={area} value={area}>
              {area}
            </option>
          ))}
        </select>
      </section>

      {/* Violation Type Filter — specific types grouped under their family */}
      <section className="alerts-filter-sidebar__section">
        <h3 className="alerts-filter-sidebar__section-title">Type</h3>
        <select
          value={filters.violationType}
          onChange={(e) => handleTypeChange(e.target.value)}
          className="alerts-filter-sidebar__select"
          aria-label="Violation type"
        >
          <option value="">All Types</option>
          {typeEntries.map((entry) =>
            entry.kind === 'option' ? (
              <option key={entry.option.value} value={entry.option.value}>
                {entry.option.label}
              </option>
            ) : (
              <optgroup key={entry.label} label={entry.label}>
                {entry.options.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </optgroup>
            )
          )}
        </select>
        {typeOptionsLoading && (
          <span className="alerts-filter-sidebar__loading">Loading types...</span>
        )}
      </section>
    </aside>
  );
}
