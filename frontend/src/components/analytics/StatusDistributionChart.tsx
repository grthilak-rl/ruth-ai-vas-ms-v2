/**
 * Status Distribution Donut Chart
 *
 * Per analytics-design.md §5.2.5:
 * - Donut chart showing violation status distribution
 * - Segments: Open, Reviewed, Dismissed, Resolved
 * - Click segment to filter (optional)
 * - Hover shows percentage and count
 *
 * Implemented with SVG for lightweight rendering without external dependencies.
 */

import { useState, useMemo } from 'react';
import type { StatusBreakdown } from '../../types/analytics';
import './StatusDistributionChart.css';

interface StatusDistributionChartProps {
  /** Status breakdown data from analytics summary */
  byStatus: StatusBreakdown[];
  /** Loading state */
  isLoading?: boolean;
  /** Optional callback when segment is clicked */
  onSegmentClick?: (status: string) => void;
}

/** Status colors matching the design system */
const STATUS_COLORS: Record<string, string> = {
  open: '#EF4444', // Red
  reviewed: '#F59E0B', // Amber
  dismissed: '#6B7280', // Gray
  resolved: '#22C55E', // Green
};

/** Get color for a status */
function getStatusColor(status: string): string {
  return STATUS_COLORS[status.toLowerCase()] || '#9CA3AF';
}

/** Humanize status for display */
function humanizeStatus(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1).toLowerCase();
}

/** Calculate SVG arc path for a donut segment */
function describeArc(
  cx: number,
  cy: number,
  outerRadius: number,
  innerRadius: number,
  startAngle: number,
  endAngle: number
): string {
  // Handle full circle case
  if (endAngle - startAngle >= 360) {
    endAngle = startAngle + 359.999;
  }

  const startRad = ((startAngle - 90) * Math.PI) / 180;
  const endRad = ((endAngle - 90) * Math.PI) / 180;

  const outerStartX = cx + outerRadius * Math.cos(startRad);
  const outerStartY = cy + outerRadius * Math.sin(startRad);
  const outerEndX = cx + outerRadius * Math.cos(endRad);
  const outerEndY = cy + outerRadius * Math.sin(endRad);

  const innerStartX = cx + innerRadius * Math.cos(endRad);
  const innerStartY = cy + innerRadius * Math.sin(endRad);
  const innerEndX = cx + innerRadius * Math.cos(startRad);
  const innerEndY = cy + innerRadius * Math.sin(startRad);

  const largeArcFlag = endAngle - startAngle > 180 ? 1 : 0;

  return [
    `M ${outerStartX} ${outerStartY}`,
    `A ${outerRadius} ${outerRadius} 0 ${largeArcFlag} 1 ${outerEndX} ${outerEndY}`,
    `L ${innerStartX} ${innerStartY}`,
    `A ${innerRadius} ${innerRadius} 0 ${largeArcFlag} 0 ${innerEndX} ${innerEndY}`,
    'Z',
  ].join(' ');
}

export function StatusDistributionChart({
  byStatus,
  isLoading = false,
  onSegmentClick,
}: StatusDistributionChartProps) {
  const [hoveredStatus, setHoveredStatus] = useState<string | null>(null);

  // Chart dimensions
  const size = 200;
  const cx = size / 2;
  const cy = size / 2;
  const outerRadius = 80;
  const innerRadius = 50;

  // Calculate total and segments
  const { total, segments } = useMemo(() => {
    const totalCount = byStatus.reduce((sum, s) => sum + s.count, 0);

    let currentAngle = 0;
    const segs = byStatus.map((status) => {
      const angle = totalCount > 0 ? (status.count / totalCount) * 360 : 0;
      const segment = {
        ...status,
        startAngle: currentAngle,
        endAngle: currentAngle + angle,
        color: getStatusColor(status.status),
      };
      currentAngle += angle;
      return segment;
    });

    return { total: totalCount, segments: segs };
  }, [byStatus]);

  // Loading state
  if (isLoading) {
    return (
      <div className="status-chart status-chart--loading">
        <div className="status-chart__skeleton" />
      </div>
    );
  }

  // Empty state
  if (byStatus.length === 0 || total === 0) {
    return (
      <div className="status-chart status-chart--empty">
        <p>No status data available</p>
      </div>
    );
  }

  return (
    <div className="status-chart">
      <div className="status-chart__container">
        <svg
          viewBox={`0 0 ${size} ${size}`}
          className="status-chart__svg"
          aria-label="Violation status distribution chart"
        >
          {/* Donut segments */}
          {segments.map((segment) => {
            const isHovered = hoveredStatus === segment.status;
            const path = describeArc(
              cx,
              cy,
              isHovered ? outerRadius + 5 : outerRadius,
              innerRadius,
              segment.startAngle,
              segment.endAngle
            );

            return (
              <path
                key={segment.status}
                d={path}
                fill={segment.color}
                className="status-chart__segment"
                opacity={
                  hoveredStatus === null || isHovered ? 1 : 0.5
                }
                onMouseEnter={() => setHoveredStatus(segment.status)}
                onMouseLeave={() => setHoveredStatus(null)}
                onClick={() => onSegmentClick?.(segment.status)}
                role="button"
                tabIndex={0}
                aria-label={`${humanizeStatus(segment.status)}: ${segment.count} (${segment.percentage}%)`}
              />
            );
          })}

          {/* Center text */}
          <text
            x={cx}
            y={cy - 8}
            textAnchor="middle"
            className="status-chart__center-value"
          >
            {total}
          </text>
          <text
            x={cx}
            y={cy + 12}
            textAnchor="middle"
            className="status-chart__center-label"
          >
            total
          </text>
        </svg>

        {/* Tooltip on hover */}
        {hoveredStatus && (
          <div className="status-chart__hover-info">
            {(() => {
              const segment = segments.find((s) => s.status === hoveredStatus);
              if (!segment) return null;
              return (
                <>
                  <span
                    className="status-chart__hover-dot"
                    style={{ backgroundColor: segment.color }}
                  />
                  <span className="status-chart__hover-text">
                    {humanizeStatus(segment.status)}: {segment.count} (
                    {segment.percentage}%)
                  </span>
                </>
              );
            })()}
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="status-chart__legend">
        {segments.map((segment) => (
          <div
            key={segment.status}
            className={`status-chart__legend-item ${
              hoveredStatus === segment.status
                ? 'status-chart__legend-item--active'
                : ''
            }`}
            onMouseEnter={() => setHoveredStatus(segment.status)}
            onMouseLeave={() => setHoveredStatus(null)}
            onClick={() => onSegmentClick?.(segment.status)}
            role="button"
            tabIndex={0}
          >
            <span
              className="status-chart__legend-color"
              style={{ backgroundColor: segment.color }}
            />
            <span className="status-chart__legend-label">
              {humanizeStatus(segment.status)}
            </span>
            <span className="status-chart__legend-value">
              {segment.count} ({segment.percentage}%)
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
