/**
 * Analytics Dashboard Page
 * F2 Path: /analytics
 * Operational analytics and summary dashboards.
 *
 * Per analytics-design.md:
 * - Executive Summary cards (Detection Rate, Response Time, Coverage, Health)
 * - Dashboard summary with time range selector
 * - KPI cards (Total, Open, Reviewed, Dismissed, Resolved, Active Cameras)
 * - Violations Over Time chart
 * - By Status pie chart
 * - Camera Performance breakdown
 * - Violation Types breakdown
 * - Export Data functionality
 */

import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  TimeRangeSelector,
  AnalyticsSummaryCards,
  SimpleBarChart,
  ViolationsOverTimeChart,
  StatusDistributionChart,
  ExecutiveSummaryCards,
  type BarChartData,
} from '../components/analytics';
import { ErrorState } from '../components/ui';
import {
  getAnalyticsSummary,
  calculateTimeRange,
} from '../services/analyticsApi';
import type {
  AnalyticsSummaryResponse,
  TimeRangePreset,
  TimeRange,
} from '../types/analytics';
import './AnalyticsPage.css';

export function AnalyticsPage() {
  const [preset, setPreset] = useState<TimeRangePreset>('24h');
  const [customFrom, setCustomFrom] = useState<Date | undefined>();
  const [customTo, setCustomTo] = useState<Date | undefined>();
  const [data, setData] = useState<AnalyticsSummaryResponse | null>(null);
  const [currentTimeRange, setCurrentTimeRange] = useState<TimeRange | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [systemHealth, setSystemHealth] = useState<'healthy' | 'degraded' | 'unhealthy' | 'unknown'>('unknown');

  // Fetch system health status
  const fetchHealthStatus = async () => {
    try {
      const response = await fetch('/api/v1/health');
      if (response.ok) {
        const healthData = await response.json();
        if (healthData.status === 'healthy') {
          setSystemHealth('healthy');
        } else {
          // Check components
          const components = healthData.components || {};
          const hasUnhealthy = Object.values(components).some(
            (status) => status === 'unhealthy'
          );
          setSystemHealth(hasUnhealthy ? 'unhealthy' : 'degraded');
        }
      } else {
        setSystemHealth('unknown');
      }
    } catch {
      setSystemHealth('unknown');
    }
  };

  // Fetch analytics data
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
        const range = calculateTimeRange(preset);
        from = range.from;
        to = range.to;
      } else {
        // Custom selected but dates not set yet
        setIsLoading(false);
        return;
      }

      setCurrentTimeRange({ from, to });
      const granularity = preset === '24h' ? 'hour' : 'day';
      const response = await getAnalyticsSummary(from, to, granularity);
      setData(response);
      setLastUpdated(new Date());
    } catch (error) {
      console.error('Failed to fetch analytics:', error);
      setIsError(true);
    } finally {
      setIsLoading(false);
    }
  };

  // Fetch on mount and when time range changes (for presets)
  useEffect(() => {
    if (preset !== 'custom') {
      fetchData();
    }
    fetchHealthStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset]);

  // Auto-refresh every 60 seconds (per analytics-design.md §13.3)
  useEffect(() => {
    const interval = setInterval(() => {
      if (!isLoading && !isError) {
        fetchData();
        fetchHealthStatus();
      }
    }, 60000);

    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading, isError]);

  const handlePresetChange = (newPreset: TimeRangePreset) => {
    setPreset(newPreset);
  };

  const handleCustomRangeApply = (from: Date, to: Date) => {
    setCustomFrom(from);
    setCustomTo(to);
    setPreset('custom');
    fetchData();
  };

  const handleRetry = () => {
    fetchData();
  };

  // Prepare chart data
  const cameraChartData: BarChartData[] =
    data?.by_camera.map((cam) => ({
      label: cam.camera_name,
      value: cam.violations_total,
    })) ?? [];

  const typeChartData: BarChartData[] =
    data?.by_type.map((type) => ({
      label: type.type_display,
      value: type.count,
      percentage: type.percentage,
    })) ?? [];

  // Determine granularity based on preset
  const granularity = preset === '24h' ? 'hour' : 'day';

  // Calculate staleness (per F6 §6.3 and analytics-design.md §5.7)
  const staleness = data?.generated_at
    ? Math.floor((Date.now() - new Date(data.generated_at).getTime()) / 1000)
    : null;
  const isStale = staleness !== null && staleness > 300; // > 5 minutes
  const showStalenessIndicator = staleness !== null && staleness > 60; // > 1 minute

  // Error state
  if (isError) {
    return (
      <div className="analytics-page">
        <ErrorState
          message="Unable to load analytics data"
          hint="Could not retrieve analytics summary. This may be a temporary issue."
          onRetry={handleRetry}
        />
      </div>
    );
  }

  return (
    <div className="analytics-page">
      {isStale && (
        <div className="analytics-page__stale-banner">
          <span>Data may be outdated. Unable to refresh automatically.</span>
          <button
            type="button"
            className="analytics-page__refresh-btn"
            onClick={fetchData}
          >
            Retry Now
          </button>
        </div>
      )}

      {/* Time Range Card with Actions */}
      <div className="analytics-time-range-card">
        <div className="analytics-time-range-card__left">
          <TimeRangeSelector
            selectedPreset={preset}
            customFrom={customFrom}
            customTo={customTo}
            onPresetChange={handlePresetChange}
            onCustomRangeApply={handleCustomRangeApply}
            disabled={isLoading}
          />
          {showStalenessIndicator && lastUpdated && (
            <span
              className={`analytics-time-range-card__staleness ${isStale ? 'analytics-time-range-card__staleness--warning' : ''}`}
            >
              Last: {formatTimeAgo(staleness!)} ago
            </span>
          )}
        </div>
        <div className="analytics-time-range-card__actions">
          <button
            type="button"
            className="analytics-page__refresh-btn-icon"
            onClick={fetchData}
            disabled={isLoading}
            title="Refresh data"
            aria-label="Refresh analytics data"
          >
            ⟳
          </button>
          <Link to="/analytics/export" className="analytics-page__export-link">
            Export Data →
          </Link>
        </div>
      </div>

      {/* Executive Summary Cards (Hero KPIs) */}
      <ExecutiveSummaryCards
        summary={data}
        timeRange={currentTimeRange}
        isLoading={isLoading}
        systemHealth={systemHealth}
      />

      {/* Detailed Summary Cards */}
      <AnalyticsSummaryCards
        totals={data?.totals ?? null}
        comparison={data?.comparison ?? null}
        isLoading={isLoading}
        isError={false}
      />

      {/* Empty state */}
      {!isLoading && data && data.totals.violations_total === 0 && (
        <div className="analytics-page__empty">
          <h2>No violations in the selected time range</h2>
          <p>
            Try a different time range or check the Violations page with a wider
            date filter.
          </p>
          <Link to="/alerts" className="analytics-page__link-btn">
            View Violations →
          </Link>
        </div>
      )}

      {/* Charts - only show if we have data */}
      {!isLoading && data && data.totals.violations_total > 0 && (
        <>
          {/* Primary Charts Row: Violations Over Time + Status Distribution */}
          <div className="analytics-page__primary-charts">
            <div className="analytics-page__chart-card analytics-page__chart-card--wide">
              <h2 className="analytics-page__chart-title">
                Violations Over Time
              </h2>
              <ViolationsOverTimeChart
                timeSeries={data.time_series}
                granularity={granularity}
                isLoading={isLoading}
              />
            </div>

            <div className="analytics-page__chart-card analytics-page__chart-card--narrow">
              <h2 className="analytics-page__chart-title">By Status</h2>
              <StatusDistributionChart
                byStatus={data.by_status}
                isLoading={isLoading}
              />
            </div>
          </div>

          {/* Secondary Charts Row: By Camera + By Type */}
          <div className="analytics-page__charts">
            <div className="analytics-page__chart-card">
              <h2 className="analytics-page__chart-title">
                By Camera (Top 5)
              </h2>
              <SimpleBarChart
                data={cameraChartData}
                maxItems={5}
                isLoading={isLoading}
                isError={false}
              />
              <div className="analytics-page__chart-footer">
                <Link to="/analytics/cameras">View All Cameras →</Link>
              </div>
            </div>

            <div className="analytics-page__chart-card">
              <h2 className="analytics-page__chart-title">
                By Violation Type
              </h2>
              <SimpleBarChart
                data={typeChartData}
                maxItems={10}
                isLoading={isLoading}
                isError={false}
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function formatTimeAgo(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h`;
}
