/**
 * Violations Over Time Line Chart
 *
 * Per analytics-design.md §5.2.3:
 * - Line chart with time on X-axis, count on Y-axis
 * - Multiple series: one per violation type
 * - Hover shows tooltip with exact count and timestamp
 * - Granularity options: hour (default for 24h), day (for 7d/30d)
 *
 * Implemented with SVG for lightweight rendering without external dependencies.
 */

import { useState, useMemo } from 'react';
import type { TimeSeriesBucket } from '../../types/analytics';
import './ViolationsOverTimeChart.css';

interface ViolationsOverTimeChartProps {
  /** Time series data from analytics summary */
  timeSeries: TimeSeriesBucket[];
  /** Granularity of time buckets */
  granularity: 'hour' | 'day';
  /** Loading state */
  isLoading?: boolean;
  /** Optional callback when data point is clicked */
  onDataPointClick?: (bucket: TimeSeriesBucket) => void;
}

/** Chart colors for different violation types */
const TYPE_COLORS: Record<string, string> = {
  fall_detected: '#EF4444', // Red
  ppe_missing: '#F59E0B', // Amber
  unauthorized_entry: '#8B5CF6', // Purple
  default: '#3B82F6', // Blue
};

/** Get color for a violation type */
function getTypeColor(type: string): string {
  return TYPE_COLORS[type] || TYPE_COLORS.default;
}

/** Format timestamp for display */
function formatTimestamp(isoString: string, granularity: 'hour' | 'day'): string {
  const date = new Date(isoString);
  if (granularity === 'hour') {
    return date.toLocaleTimeString('en-US', { hour: 'numeric', hour12: true });
  }
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/** Format full timestamp for tooltip */
function formatFullTimestamp(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

/** Humanize violation type for display */
function humanizeType(type: string): string {
  return type
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export function ViolationsOverTimeChart({
  timeSeries,
  granularity,
  isLoading = false,
  onDataPointClick,
}: ViolationsOverTimeChartProps) {
  const [hoveredPoint, setHoveredPoint] = useState<{
    x: number;
    y: number;
    bucket: TimeSeriesBucket;
  } | null>(null);

  // Chart dimensions
  const width = 800;
  const height = 300;
  const padding = { top: 20, right: 20, bottom: 50, left: 50 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  // Extract unique violation types from data
  const violationTypes = useMemo(() => {
    const types = new Set<string>();
    timeSeries.forEach((bucket) => {
      Object.keys(bucket.by_type).forEach((type) => types.add(type));
    });
    return Array.from(types);
  }, [timeSeries]);

  // Calculate scales
  const { xScale, yScale, maxValue } = useMemo(() => {
    const dataLength = timeSeries.length;
    const max = Math.max(...timeSeries.map((b) => b.total), 1);

    return {
      xScale: (index: number) =>
        padding.left + (index / Math.max(dataLength - 1, 1)) * chartWidth,
      yScale: (value: number) =>
        padding.top + chartHeight - (value / max) * chartHeight,
      maxValue: max,
    };
  }, [timeSeries, chartWidth, chartHeight]);

  // Generate Y-axis ticks
  const yTicks = useMemo(() => {
    const tickCount = 5;
    const ticks: number[] = [];
    for (let i = 0; i <= tickCount; i++) {
      ticks.push(Math.round((maxValue * i) / tickCount));
    }
    return ticks;
  }, [maxValue]);

  // Generate path for a line series
  const generatePath = (
    data: TimeSeriesBucket[],
    getValue: (bucket: TimeSeriesBucket) => number
  ): string => {
    if (data.length === 0) return '';

    return data
      .map((bucket, index) => {
        const x = xScale(index);
        const y = yScale(getValue(bucket));
        return `${index === 0 ? 'M' : 'L'} ${x} ${y}`;
      })
      .join(' ');
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="violations-chart violations-chart--loading">
        <div className="violations-chart__skeleton" />
      </div>
    );
  }

  // Empty state
  if (timeSeries.length === 0) {
    return (
      <div className="violations-chart violations-chart--empty">
        <p>No time series data available</p>
      </div>
    );
  }

  return (
    <div className="violations-chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="violations-chart__svg"
        aria-label="Violations over time chart"
      >
        {/* Y-axis grid lines and labels */}
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              x1={padding.left}
              y1={yScale(tick)}
              x2={width - padding.right}
              y2={yScale(tick)}
              className="violations-chart__grid-line"
            />
            <text
              x={padding.left - 10}
              y={yScale(tick)}
              className="violations-chart__axis-label"
              textAnchor="end"
              dominantBaseline="middle"
            >
              {tick}
            </text>
          </g>
        ))}

        {/* X-axis labels */}
        {timeSeries.map((bucket, index) => {
          // Only show some labels to avoid overcrowding
          const showLabel =
            timeSeries.length <= 12 ||
            index % Math.ceil(timeSeries.length / 12) === 0;

          if (!showLabel) return null;

          return (
            <text
              key={bucket.bucket}
              x={xScale(index)}
              y={height - padding.bottom + 20}
              className="violations-chart__axis-label"
              textAnchor="middle"
            >
              {formatTimestamp(bucket.bucket, granularity)}
            </text>
          );
        })}

        {/* Total line (main line) */}
        <path
          d={generatePath(timeSeries, (b) => b.total)}
          className="violations-chart__line violations-chart__line--total"
          fill="none"
          strokeWidth="2"
        />

        {/* Lines for each violation type */}
        {violationTypes.map((type) => (
          <path
            key={type}
            d={generatePath(timeSeries, (b) => b.by_type[type] || 0)}
            className="violations-chart__line"
            fill="none"
            strokeWidth="1.5"
            stroke={getTypeColor(type)}
            strokeDasharray="4 2"
            opacity="0.7"
          />
        ))}

        {/* Data points (circles) for interaction */}
        {timeSeries.map((bucket, index) => {
          const x = xScale(index);
          const y = yScale(bucket.total);

          return (
            <circle
              key={bucket.bucket}
              cx={x}
              cy={y}
              r="6"
              className="violations-chart__point"
              onMouseEnter={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                setHoveredPoint({
                  x: rect.left + rect.width / 2,
                  y: rect.top,
                  bucket,
                });
              }}
              onMouseLeave={() => setHoveredPoint(null)}
              onClick={() => onDataPointClick?.(bucket)}
              role="button"
              tabIndex={0}
              aria-label={`${bucket.total} violations at ${formatFullTimestamp(bucket.bucket)}`}
            />
          );
        })}
      </svg>

      {/* Legend */}
      <div className="violations-chart__legend">
        <div className="violations-chart__legend-item">
          <span
            className="violations-chart__legend-color"
            style={{ backgroundColor: '#3B82F6' }}
          />
          <span>Total</span>
        </div>
        {violationTypes.map((type) => (
          <div key={type} className="violations-chart__legend-item">
            <span
              className="violations-chart__legend-color"
              style={{ backgroundColor: getTypeColor(type) }}
            />
            <span>{humanizeType(type)}</span>
          </div>
        ))}
      </div>

      {/* Tooltip */}
      {hoveredPoint && (
        <div
          className="violations-chart__tooltip"
          style={{
            position: 'fixed',
            left: hoveredPoint.x,
            top: hoveredPoint.y - 10,
            transform: 'translate(-50%, -100%)',
          }}
        >
          <div className="violations-chart__tooltip-header">
            {formatFullTimestamp(hoveredPoint.bucket.bucket)}
          </div>
          <div className="violations-chart__tooltip-content">
            <div className="violations-chart__tooltip-row">
              <span>Total:</span>
              <strong>{hoveredPoint.bucket.total}</strong>
            </div>
            {Object.entries(hoveredPoint.bucket.by_type).map(([type, count]) => (
              <div key={type} className="violations-chart__tooltip-row">
                <span style={{ color: getTypeColor(type) }}>
                  {humanizeType(type)}:
                </span>
                <span>{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
