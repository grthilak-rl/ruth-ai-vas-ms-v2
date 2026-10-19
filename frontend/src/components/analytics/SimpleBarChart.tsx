/**
 * Simple Bar Chart Component
 *
 * Lightweight bar chart implementation without external dependencies.
 * Used for camera breakdown and violation type displays.
 */

import './SimpleBarChart.css';

export interface BarChartData {
  label: string;
  value: number;
  percentage?: number;
  /** Smaller second line under the label, e.g. the family of a specific type */
  sublabel?: string;
  /** Hover text when the label is cut short; defaults to the label */
  title?: string;
}

interface SimpleBarChartProps {
  data: BarChartData[];
  maxItems?: number;
  isLoading?: boolean;
  isError?: boolean;
}

export function SimpleBarChart({
  data,
  maxItems = 5,
  isLoading = false,
  isError = false,
}: SimpleBarChartProps) {
  if (isLoading) {
    return (
      <div className="simple-bar-chart simple-bar-chart--loading">
        {Array.from({ length: maxItems }).map((_, i) => (
          <div key={i} className="simple-bar-chart__skeleton" />
        ))}
      </div>
    );
  }

  if (isError || data.length === 0) {
    return (
      <div className="simple-bar-chart simple-bar-chart--empty">
        <p>No data available</p>
      </div>
    );
  }

  const displayData = data.slice(0, maxItems);
  const maxValue = Math.max(...displayData.map((d) => d.value));

  return (
    <div className="simple-bar-chart">
      {displayData.map((item, index) => {
        const barWidth = maxValue > 0 ? (item.value / maxValue) * 100 : 0;

        return (
          <div key={index} className="simple-bar-chart__row">
            <div className="simple-bar-chart__label" title={item.title ?? item.label}>
              {item.label}
              {item.sublabel && (
                <span className="simple-bar-chart__sublabel">{item.sublabel}</span>
              )}
            </div>
            <div className="simple-bar-chart__bar-container">
              <div
                className="simple-bar-chart__bar"
                style={{ width: `${barWidth}%` }}
              />
            </div>
            <div className="simple-bar-chart__value">
              {item.value}
              {item.percentage !== undefined && (
                <span className="simple-bar-chart__percentage">
                  {' '}
                  ({item.percentage}%)
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
