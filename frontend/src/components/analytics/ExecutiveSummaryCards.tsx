/**
 * Executive Summary Cards
 *
 * Hero KPI cards for management overview:
 * - Detection Rate (violations per day)
 * - Avg Response Time (time to acknowledge)
 * - Camera Coverage (online vs total)
 * - System Health (from health endpoint)
 *
 * Per analytics-design.md and user requirements for management insights.
 */

import { useMemo } from 'react';
import type { AnalyticsSummaryResponse, TimeRange } from '../../types/analytics';
import './ExecutiveSummaryCards.css';

interface ExecutiveSummaryCardsProps {
  /** Analytics summary data */
  summary: AnalyticsSummaryResponse | null;
  /** Time range for calculating rates */
  timeRange: TimeRange | null;
  /** Loading state */
  isLoading?: boolean;
  /** System health status (from /health endpoint) */
  systemHealth?: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
}

/**
 * Calculate number of days in time range
 */
function getDaysInRange(timeRange: TimeRange): number {
  const from = new Date(timeRange.from);
  const to = new Date(timeRange.to);
  const diffMs = to.getTime() - from.getTime();
  const days = diffMs / (1000 * 60 * 60 * 24);
  return Math.max(days, 1); // At least 1 day
}

/**
 * Format rate for display
 */
function formatRate(rate: number): string {
  if (rate < 1) {
    return '<1';
  }
  return rate.toFixed(rate >= 10 ? 0 : 1);
}

/**
 * Format duration in seconds to human-readable string
 */
function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return '--';
  }

  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);

  if (minutes < 60) {
    return remainingSeconds > 0
      ? `${minutes}m ${remainingSeconds}s`
      : `${minutes}m`;
  }

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes > 0
    ? `${hours}h ${remainingMinutes}m`
    : `${hours}h`;
}

/**
 * Get health status display text and style
 */
function getHealthDisplay(status: string | undefined): {
  text: string;
  className: string;
} {
  switch (status) {
    case 'healthy':
      return { text: 'All Systems OK', className: 'executive-card--healthy' };
    case 'degraded':
      return { text: 'Degraded', className: 'executive-card--degraded' };
    case 'unhealthy':
      return { text: 'Unhealthy', className: 'executive-card--unhealthy' };
    default:
      return { text: 'Unknown', className: 'executive-card--unknown' };
  }
}

export function ExecutiveSummaryCards({
  summary,
  timeRange,
  isLoading = false,
  systemHealth = 'unknown',
}: ExecutiveSummaryCardsProps) {
  // Calculate derived metrics
  const metrics = useMemo(() => {
    if (!summary || !timeRange) {
      return {
        detectionRate: null,
        avgResponseTime: null,
        cameraCoverage: null,
        coveragePercent: null,
      };
    }

    const days = getDaysInRange(timeRange);
    const detectionRate = summary.totals.violations_total / days;

    // Response time: not available in current API, will show placeholder
    // This would come from summary.response_metrics.avg_response_time_seconds
    const avgResponseTime = null;

    const cameraCoverage = {
      active: summary.totals.cameras_active,
      total: summary.totals.cameras_total,
    };

    const coveragePercent =
      cameraCoverage.total > 0
        ? Math.round((cameraCoverage.active / cameraCoverage.total) * 100)
        : 0;

    return {
      detectionRate,
      avgResponseTime,
      cameraCoverage,
      coveragePercent,
    };
  }, [summary, timeRange]);

  const healthDisplay = getHealthDisplay(systemHealth);

  // Loading state
  if (isLoading) {
    return (
      <div className="executive-summary-cards">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="executive-card executive-card--loading">
            <div className="executive-card__label-skeleton" />
            <div className="executive-card__value-skeleton" />
            <div className="executive-card__meta-skeleton" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="executive-summary-cards">
      {/* Detection Rate */}
      <div className="executive-card">
        <div className="executive-card__label">Detection Rate</div>
        <div className="executive-card__value">
          {metrics.detectionRate !== null
            ? `${formatRate(metrics.detectionRate)}/day`
            : '--'}
        </div>
        <div className="executive-card__meta">
          {summary?.totals.violations_total ?? 0} violations in period
        </div>
      </div>

      {/* Avg Response Time */}
      <div className="executive-card">
        <div className="executive-card__label">Avg Response Time</div>
        <div className="executive-card__value">
          {formatDuration(metrics.avgResponseTime)}
        </div>
        <div className="executive-card__meta executive-card__meta--coming-soon">
          Response tracking coming soon
        </div>
      </div>

      {/* Camera Coverage */}
      <div className="executive-card">
        <div className="executive-card__label">Camera Coverage</div>
        <div className="executive-card__value">
          {metrics.cameraCoverage
            ? `${metrics.cameraCoverage.active} / ${metrics.cameraCoverage.total}`
            : '--'}
        </div>
        <div className="executive-card__meta">
          {metrics.coveragePercent !== null
            ? `${metrics.coveragePercent}% online`
            : '--'}
        </div>
      </div>

      {/* System Health */}
      <div className={`executive-card ${healthDisplay.className}`}>
        <div className="executive-card__label">System Health</div>
        <div className="executive-card__value executive-card__value--status">
          <span className="executive-card__status-dot" />
          {healthDisplay.text}
        </div>
        <div className="executive-card__meta">
          {systemHealth === 'healthy'
            ? 'All services operational'
            : systemHealth === 'degraded'
              ? 'Some services degraded'
              : systemHealth === 'unhealthy'
                ? 'Critical issues detected'
                : 'Status unavailable'}
        </div>
      </div>
    </div>
  );
}
