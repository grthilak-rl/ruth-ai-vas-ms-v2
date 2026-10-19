import type { IncidentSummary } from '../../state/api';
import './SummaryStrip.css';

interface SummaryStripProps {
  summary: IncidentSummary | undefined;
  incidents: number;
  violations: number;
  gapMinutes: number;
  /** "last 7 days", "today", … */
  rangeLabel: string;
}

const n = (value: number) => value.toLocaleString('en-US');

/**
 * Totals for the current filters, across every page: what needs attention
 * before scrolling. Severity counts are incidents (what an operator works
 * through); the tooltip gives the violations behind them.
 */
export function SummaryStrip({ summary, incidents, violations, gapMinutes, rangeLabel }: SummaryStripProps) {
  return (
    <section className="summary-strip" aria-label="Summary for the current filters">
      <dl className="summary-strip__stats">
        <div className="summary-strip__stat">
          <dt>Incidents</dt>
          <dd>{n(incidents)}</dd>
        </div>
        <div className="summary-strip__stat">
          <dt>Violations</dt>
          <dd>{n(violations)}</dd>
        </div>
        {summary && (
          <>
            <div className="summary-strip__stat">
              <dt>Open</dt>
              <dd>{n(summary.open_violations)}</dd>
            </div>
            <div
              className="summary-strip__stat summary-strip__stat--critical"
              title={`${n(summary.violations_by_severity.critical)} critical violations`}
            >
              <dt>Critical</dt>
              <dd>{n(summary.incidents_by_severity.critical)}</dd>
            </div>
            <div
              className="summary-strip__stat summary-strip__stat--high"
              title={`${n(summary.violations_by_severity.high)} high violations`}
            >
              <dt>High</dt>
              <dd>{n(summary.incidents_by_severity.high)}</dd>
            </div>
            <div className="summary-strip__stat">
              <dt>Cameras</dt>
              <dd>{n(summary.cameras)}</dd>
            </div>
            {summary.top_area && (
              <div className="summary-strip__stat summary-strip__stat--wide">
                <dt>Busiest area</dt>
                <dd>
                  {summary.top_area}{' '}
                  <span className="summary-strip__sub">{n(summary.top_area_violations)} violations</span>
                </dd>
              </div>
            )}
          </>
        )}
      </dl>
      <p className="summary-strip__caption">
        {rangeLabel} · repeats within {gapMinutes} min on the same camera are grouped
      </p>
    </section>
  );
}
