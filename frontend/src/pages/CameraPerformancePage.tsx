/**
 * Camera Performance Page
 * F2 Path: /analytics/cameras
 *
 * Per analytics-design.md §6:
 * - Detailed breakdown of violations per camera
 * - Sortable table with filtering
 * - Per-camera detail expandable sections
 */

import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ErrorState, LoadingState } from '../components/ui';
import { getDeviceStatus, calculateTimeRange } from '../services/analyticsApi';
import type { DeviceStatusResponse, TimeRangePreset } from '../types/analytics';
import './CameraPerformancePage.css';

export function CameraPerformancePage() {
  const [preset] = useState<TimeRangePreset>('24h');
  const [data, setData] = useState<DeviceStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);

  const fetchData = async () => {
    setIsLoading(true);
    setIsError(false);

    try {
      const range = calculateTimeRange(preset as '24h' | '7d' | '30d');
      const response = await getDeviceStatus(range.from, range.to);
      setData(response);
    } catch (error) {
      console.error('Failed to fetch device status:', error);
      setIsError(true);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset]);

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
              <th>Camera Name</th>
              <th>Total</th>
              <th>Open</th>
              <th>Reviewed</th>
              <th>Dismissed</th>
              <th>Resolved</th>
              <th>Avg Confidence</th>
            </tr>
          </thead>
          <tbody>
            {data?.devices.map((device) => (
              <tr key={device.camera_id}>
                <td className="camera-performance-table__name">{device.camera_name}</td>
                <td>{device.violations_total}</td>
                <td>{device.violations_by_status.open ?? 0}</td>
                <td>{device.violations_by_status.reviewed ?? 0}</td>
                <td>{device.violations_by_status.dismissed ?? 0}</td>
                <td>{device.violations_by_status.resolved ?? 0}</td>
                <td>{(device.avg_confidence * 100).toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>

        {data?.devices.length === 0 && (
          <div className="camera-performance-page__empty">
            No camera data available for the selected time range.
          </div>
        )}
      </div>
    </div>
  );
}
