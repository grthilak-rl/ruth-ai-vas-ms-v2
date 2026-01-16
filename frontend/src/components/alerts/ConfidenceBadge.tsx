import type { ConfidenceCategory } from '../../state/api';
import './ConfidenceBadge.css';

interface ConfidenceBadgeProps {
  category: ConfidenceCategory;
  label: string;
}

/**
 * Confidence Badge Component (F4/F6-aligned)
 *
 * Displays categorical confidence: High, Medium, Low.
 *
 * HARD RULE (F6 §3.2):
 * - MUST NOT display raw confidence numbers (0.87, 87%, etc.)
 * - Always use categorical labels
 *
 * Visual treatment per F4:
 * - High: Solid prominent color
 * - Medium: Standard styling
 * - Low: Muted styling
 */
export function ConfidenceBadge({ category, label }: ConfidenceBadgeProps) {
  return (
    <span
      className={`confidence-badge confidence-badge--${category}`}
      aria-label={`${label} confidence`}
    >
      {label}
    </span>
  );
}
