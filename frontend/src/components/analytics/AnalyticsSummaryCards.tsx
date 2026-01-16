/**
 * Analytics Summary Cards Component
 *
 * Per analytics-design.md §5.2.2
 * - Display 6 KPI cards
 * - Show comparison to previous period
 * - Handle loading, error, and null states
 */

import type { AnalyticsTotals, AnalyticsComparison } from '../../types/analytics';
import './AnalyticsSummaryCards.css';

interface AnalyticsSummaryCardsProps {
  totals: AnalyticsTotals | null;
  comparison: AnalyticsComparison | null;
  isLoading?: boolean;
  isError?: boolean;
}

export function AnalyticsSummaryCards({
  totals,
  comparison,
  isLoading = false,
  isError = false,
}: AnalyticsSummaryCardsProps) {
  const cards = [
    {
      title: 'Total Violations',
      value: totals?.violations_total ?? null,
      comparison: comparison?.violations_total_change,
      comparisonPercent: comparison?.violations_total_change_percent,
    },
    {
      title: 'Open Violations',
      value: totals?.violations_open ?? null,
    },
    {
      title: 'Reviewed Violations',
      value: totals?.violations_reviewed ?? null,
    },
    {
      title: 'Dismissed Violations',
      value: totals?.violations_dismissed ?? null,
    },
    {
      title: 'Resolved Violations',
      value: totals?.violations_resolved ?? null,
    },
    {
      title: 'Active Cameras',
      value: totals?.cameras_active ?? null,
      secondaryValue: totals?.cameras_total ?? null,
      variant: 'ratio' as const,
    },
  ];

  return (
    <div className="analytics-summary-cards">
      {cards.map((card, index) => (
        <AnalyticsCard
          key={index}
          title={card.title}
          value={card.value}
          secondaryValue={card.secondaryValue}
          variant={card.variant}
          comparison={card.comparison}
          comparisonPercent={card.comparisonPercent}
          isLoading={isLoading}
          isError={isError}
        />
      ))}
    </div>
  );
}

interface AnalyticsCardProps {
  title: string;
  value: number | null;
  secondaryValue?: number | null;
  variant?: 'default' | 'ratio';
  comparison?: number;
  comparisonPercent?: number;
  isLoading: boolean;
  isError: boolean;
}

function AnalyticsCard({
  title,
  value,
  secondaryValue,
  variant = 'default',
  comparison,
  comparisonPercent,
  isLoading,
  isError,
}: AnalyticsCardProps) {
  const renderValue = () => {
    if (isLoading) {
      return <div className="analytics-card__skeleton" />;
    }

    if (isError || value === null) {
      return <span className="analytics-card__value analytics-card__value--unavailable">—</span>;
    }

    if (variant === 'ratio' && secondaryValue !== null && secondaryValue !== undefined) {
      return (
        <span className="analytics-card__value">
          {value} / {secondaryValue}
        </span>
      );
    }

    return <span className="analytics-card__value">{value}</span>;
  };

  const renderComparison = () => {
    if (
      isLoading ||
      isError ||
      comparison === undefined ||
      comparisonPercent === undefined
    ) {
      return null;
    }

    const isPositive = comparison > 0;
    const isNeutral = comparison === 0;
    const symbol = isPositive ? '↑' : isNeutral ? '=' : '↓';
    const className = `analytics-card__comparison ${isPositive ? 'analytics-card__comparison--up' : isNeutral ? 'analytics-card__comparison--neutral' : 'analytics-card__comparison--down'}`;

    return (
      <div className={className}>
        {symbol} {Math.abs(comparisonPercent)}% vs prev
      </div>
    );
  };

  return (
    <div className={`analytics-card ${isLoading ? 'analytics-card--loading' : ''} ${isError ? 'analytics-card--error' : ''}`}>
      <h3 className="analytics-card__title">{title}</h3>
      <div className="analytics-card__body">{renderValue()}</div>
      {renderComparison()}
    </div>
  );
}
