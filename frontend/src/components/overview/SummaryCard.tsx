import { Link } from 'react-router-dom';
import './SummaryCard.css';

interface SummaryCardProps {
  /** Card title (e.g., "Open Alerts") */
  title: string;
  /** Primary value to display */
  value: number | null;
  /** Optional secondary value for ratio display (e.g., "8 / 10") */
  secondaryValue?: number | null;
  /** Whether data is loading */
  isLoading?: boolean;
  /** Whether data fetch failed */
  isError?: boolean;
  /** Optional link destination */
  linkTo?: string;
  /** Link label (e.g., "View All") */
  linkLabel?: string;
  /** Visual variant */
  variant?: 'default' | 'ratio';
}

/**
 * Summary Card Component (F4 §4.1)
 *
 * Displays a single metric card on the Overview dashboard.
 *
 * Per F4:
 * - Shows primary count value
 * - Optional ratio display (e.g., "8 / 10" for cameras)
 * - Optional "View All" link
 * - Loading shows skeleton
 * - Error shows "—" with degraded indicator
 *
 * Per F6 §6.2:
 * - MUST NOT perform arithmetic across different API calls
 * - Display values exactly as received
 */
export function SummaryCard({
  title,
  value,
  secondaryValue,
  isLoading = false,
  isError = false,
  linkTo,
  linkLabel = 'View All',
  variant = 'default',
}: SummaryCardProps) {
  // Determine display value
  const renderValue = () => {
    if (isLoading) {
      return <span className="summary-card__value summary-card__value--loading">...</span>;
    }

    if (isError || value === null) {
      return (
        <span className="summary-card__value summary-card__value--unavailable">
          —
        </span>
      );
    }

    if (variant === 'ratio' && secondaryValue !== null && secondaryValue !== undefined) {
      return (
        <span className="summary-card__value">
          {value} / {secondaryValue}
        </span>
      );
    }

    return <span className="summary-card__value">{value}</span>;
  };

  const cardContent = (
    <>
      <h3 className="summary-card__title">{title}</h3>
      <div className="summary-card__body">
        {renderValue()}
      </div>
      {linkTo && !isError && (
        <div className="summary-card__footer">
          <Link to={linkTo} className="summary-card__link">
            {linkLabel} &rarr;
          </Link>
        </div>
      )}
      {isError && (
        <div className="summary-card__footer summary-card__footer--error">
          <span className="summary-card__error-hint">Data unavailable</span>
        </div>
      )}
    </>
  );

  return (
    <div
      className={`summary-card ${isError ? 'summary-card--error' : ''} ${isLoading ? 'summary-card--loading' : ''}`}
    >
      {cardContent}
    </div>
  );
}
