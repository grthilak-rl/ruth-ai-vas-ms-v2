import { severityLabel, severityOrDefault } from '../../utils/violationDisplay';
import './SeverityBadge.css';

/**
 * Severity Badge — the firing rule's severity from its manifest
 * (Critical / High / Medium / Low).
 *
 * Replaces the confidence badge as the card's headline signal: confidence
 * is how sure the model is, severity is how bad the rule says it is, and
 * the old badge styled the former like the latter.
 */
export function SeverityBadge({ severity }: { severity: unknown }) {
  const level = severityOrDefault(severity);
  return (
    <span className={`severity-badge severity-badge--${level}`} aria-label={`Severity: ${severityLabel(level)}`}>
      {severityLabel(level)}
    </span>
  );
}
