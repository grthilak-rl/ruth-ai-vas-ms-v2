/**
 * Camera Performance Page
 * F2 Path: /analytics/cameras
 *
 * Per analytics-design.md §6:
 * - Detailed breakdown of violations per camera
 * - Sortable table with filtering
 * - Per-camera detail expandable sections
 * - Time range selector
 */

import { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { ErrorState, LoadingState } from '../components/ui';
import { TimeRangeSelector } from '../components/analytics';
import { getDeviceStatus, calculateTimeRange } from '../services/analyticsApi';
import type { DeviceStatusResponse, DeviceAnalytics, TimeRangePreset } from '../types/analytics';
import './CameraPerformancePage.css';

type SortField = 'camera_name' | 'violations_total' | 'open' | 'avg_confidence';
type SortOrder = 'asc' | 'desc';

export function CameraPerformancePage() {
  const [preset, setPreset] = useState<TimeRangePreset>('24h');
  const [customFrom, setCustomFrom] = useState<Date | undefined>();
  const [customTo, setCustomTo] = useState<Date | undefined>();
  const [data, setData] = useState<DeviceStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);
  const [sortField, setSortField] = useState<SortField>('violations_total');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');
  const [expandedCamera, setExpandedCamera] = useState<string | null>(null);

  const fetchData = async () => {
    setIsLoading(true);
    setIsError(false);

    try {
      let from: string;
      let to: string;

      if (preset === 'custom' && customFrom && customTo) {
        from = customFrom.toISOString();
        to = customTo.toISOString();
      } else if (preset !== 'custom') {
        const range = calculateTimeRange(preset as '24h' | '7d' | '30d');
        from = range.from;
        to = range.to;
      } else {
        setIsLoading(false);
        return;
      }

      const response = await getDeviceStatus(from, to);
      setData(response);
    } catch (error) {
      console.error('Failed to fetch device status:', error);
      setIsError(true);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (preset !== 'custom') {
      fetchData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset]);

  const handlePresetChange = (newPreset: TimeRangePreset) => {
    setPreset(newPreset);
  };

  const handleCustomRangeApply = (from: Date, to: Date) => {
    setCustomFrom(from);
    setCustomTo(to);
    setPreset('custom');
    fetchData();
  };

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder('desc');
    }
  };

  const toggleExpand = (cameraId: string) => {
    setExpandedCamera(expandedCamera === cameraId ? null : cameraId);
  };

  // Sort devices
  const sortedDevices = useMemo(() => {
    if (!data?.devices) return [];

    return [...data.devices].sort((a, b) => {
      let aVal: number | string;
      let bVal: number | string;

      switch (sortField) {
        case 'camera_name':
          aVal = a.camera_name.toLowerCase();
          bVal = b.camera_name.toLowerCase();
          break;
        case 'violations_total':
          aVal = a.violations_total;
          bVal = b.violations_total;
          break;
        case 'open':
          aVal = a.violations_by_status.open ?? 0;
          bVal = b.violations_by_status.open ?? 0;
          break;
        case 'avg_confidence':
          aVal = a.avg_confidence;
          bVal = b.avg_confidence;
          break;
        default:
          return 0;
      }

      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return sortOrder === 'asc'
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }

      return sortOrder === 'asc'
        ? (aVal as number) - (bVal as number)
        : (bVal as number) - (aVal as number);
    });
  }, [data?.devices, sortField, sortOrder]);

  const renderSortIcon = (field: SortField) => {
    if (sortField !== field) {
      return <span className="sort-icon sort-icon--inactive">⇅</span>;
    }
    return (
      <span className="sort-icon sort-icon--active">
        {sortOrder === 'asc' ? '↑' : '↓'}
      </span>
    );
  };

  if (isLoading) {
    return (
      <div className="camera-performance-page">
        <div className="camera-performance-page__header">
          <Link to="/analytics" className="camera-performance-page__back">
            ← Back to Analytics
          </Link>
          <h1>Camera Performance</h1>
        </div>
        <LoadingState message="Loading camera performance..." />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="camera-performance-page">
        <div className="camera-performance-page__header">
          <Link to="/analytics" className="camera-performance-page__back">
            ← Back to Analytics
          </Link>
          <h1>Camera Performance</h1>
        </div>
        <ErrorState
          message="Unable to load camera performance data"
          hint="Could not retrieve device status. This may be a temporary issue."
          onRetry={fetchData}
        />
      </div>
    );
  }

  return (
    <div className="camera-performance-page">
      <div className="camera-performance-page__header">
        <Link to="/analytics" className="camera-performance-page__back">
          ← Back to Analytics
        </Link>
        <h1>Camera Performance</h1>
      </div>

      <TimeRangeSelector
        selectedPreset={preset}
        customFrom={customFrom}
        customTo={customTo}
        onPresetChange={handlePresetChange}
        onCustomRangeApply={handleCustomRangeApply}
        disabled={isLoading}
      />

      <div className="camera-performance-page__summary">
        <div className="camera-performance-summary__card">
          <div className="camera-performance-summary__value">
            {data?.summary.total_violations ?? 0}
          </div>
          <div className="camera-performance-summary__label">Total Violations</div>
        </div>
        <div className="camera-performance-summary__card">
          <div className="camera-performance-summary__value">
            {data?.summary.active_cameras ?? 0} / {data?.summary.total_cameras ?? 0}
          </div>
          <div className="camera-performance-summary__label">Active Cameras</div>
        </div>
      </div>

      <div className="camera-performance-page__table">
        <table>
          <thead>
            <tr>
              <th className="camera-performance-th--expand"></th>
              <th
                className="camera-performance-th--sortable"
                onClick={() => handleSort('camera_name')}
              >
                Camera Name {renderSortIcon('camera_name')}
              </th>
              <th
                className="camera-performance-th--sortable"
                onClick={() => handleSort('violations_total')}
              >
                Total {renderSortIcon('violations_total')}
              </th>
              <th
                className="camera-performance-th--sortable"
                onClick={() => handleSort('open')}
              >
                Open {renderSortIcon('open')}
              </th>
              <th>Reviewed</th>
              <th>Dismissed</th>
              <th>Resolved</th>
              <th
                className="camera-performance-th--sortable"
                onClick={() => handleSort('avg_confidence')}
              >
                Avg Confidence {renderSortIcon('avg_confidence')}
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedDevices.map((device) => (
              <CameraRow
                key={device.camera_id}
                device={device}
                isExpanded={expandedCamera === device.camera_id}
                onToggle={() => toggleExpand(device.camera_id)}
              />
            ))}
          </tbody>
        </table>

        {sortedDevices.length === 0 && (
          <div className="camera-performance-page__empty">
            No camera data available for the selected time range.
          </div>
        )}
      </div>
    </div>
  );
}

interface CameraRowProps {
  device: DeviceAnalytics;
  isExpanded: boolean;
  onToggle: () => void;
}

function CameraRow({ device, isExpanded, onToggle }: CameraRowProps) {
  const openCount = device.violations_by_status.open ?? 0;
  const hasOpenWarning = openCount > 3;

  return (
    <>
      <tr
        className={`camera-performance-row ${isExpanded ? 'camera-performance-row--expanded' : ''}`}
        onClick={onToggle}
      >
        <td className="camera-performance-td--expand">
          <button
            type="button"
            className="camera-performance-expand-btn"
            aria-label={isExpanded ? 'Collapse details' : 'Expand details'}
          >
            {isExpanded ? '▼' : '▶'}
          </button>
        </td>
        <td className="camera-performance-table__name">{device.camera_name}</td>
        <td>{device.violations_total}</td>
        <td className={hasOpenWarning ? 'camera-performance-td--warning' : ''}>
          {openCount}
          {hasOpenWarning && ' ⚠'}
        </td>
        <td>{device.violations_by_status.reviewed ?? 0}</td>
        <td>{device.violations_by_status.dismissed ?? 0}</td>
        <td>{device.violations_by_status.resolved ?? 0}</td>
        <td>{(device.avg_confidence * 100).toFixed(0)}%</td>
      </tr>
      {isExpanded && (
        <tr className="camera-performance-details-row">
          <td colSpan={8}>
            <CameraDetailsPanel device={device} />
          </td>
        </tr>
      )}
    </>
  );
}

interface CameraDetailsPanelProps {
  device: DeviceAnalytics;
}

function CameraDetailsPanel({ device }: CameraDetailsPanelProps) {
  const violationTypes = Object.entries(device.violations_by_type);
  const maxTypeCount = Math.max(...violationTypes.map(([, count]) => count), 1);

  return (
    <div className="camera-details-panel">
      <div className="camera-details-panel__section">
        <h4 className="camera-details-panel__title">Violations by Type</h4>
        {violationTypes.length === 0 ? (
          <p className="camera-details-panel__empty">No violations recorded</p>
        ) : (
          <div className="camera-details-panel__bars">
            {violationTypes.map(([type, count]) => (
              <div key={type} className="camera-details-bar">
                <span className="camera-details-bar__label">
                  {humanizeType(type)}
                </span>
                <div className="camera-details-bar__track">
                  <div
                    className="camera-details-bar__fill"
                    style={{ width: `${(count / maxTypeCount) * 100}%` }}
                  />
                </div>
                <span className="camera-details-bar__value">{count}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="camera-details-panel__section">
        <h4 className="camera-details-panel__title">Last Violation</h4>
        <p className="camera-details-panel__text">
          {device.last_violation_at
            ? formatRelativeTime(device.last_violation_at)
            : 'No violations recorded'}
        </p>
      </div>

      <div className="camera-details-panel__actions">
        <Link
          to={`/cameras/${device.camera_id}`}
          className="camera-details-panel__link"
        >
          View Camera Details →
        </Link>
        <Link
          to={`/alerts?camera_id=${device.camera_id}`}
          className="camera-details-panel__link"
        >
          View Violations →
        </Link>
      </div>
    </div>
  );
}

function humanizeType(type: string): string {
  return type
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMinutes = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMinutes < 1) return 'Just now';
  if (diffMinutes < 60) return `${diffMinutes} minute${diffMinutes > 1 ? 's' : ''} ago`;
  if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
  if (diffDays < 7) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined,
  });
}
