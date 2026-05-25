/**
 * Tank Overflow result visualization (Phase D.4).
 *
 * Renders a completed ``tank_overflow_monitoring`` analysis as:
 *   1. Stat cards (peak / final / duration / frames)
 *   2. Time-to-thresholds row
 *   3. Fill-level chart over time with zone coloring + threshold lines
 *   4. Model details footer
 *   5. Collapsible raw-summary panel
 *
 * Static chart only — no playback synchronization, no scrubbing. A
 * later phase will hook the chart to a video player.
 */

import { useMemo, useState } from 'react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from 'recharts';

import type { TankOverflowSummary as TankSummary } from '../../state/api/bookmarkAnalyses.api';
import { formatDuration, formatTimestamp } from '../../utils/timeFormat';
import { RawJsonSummary } from './RawJsonSummary';
import './TankOverflowSummary.css';

// Match the portal's existing Material-ish palette (see system-health
// + overview CSS for the established greens/ambers/reds).
const COLOR_OK = '#34a853';
const COLOR_WARN = '#f9a825';
const COLOR_ALERT = '#d93025';
const COLOR_GRID = '#e0e0e0';
const COLOR_TEXT = '#5f6368';

const THRESHOLD_WARN = 80;
const THRESHOLD_ALERT = 90;

interface TankOverflowSummaryProps {
  summary: TankSummary;
}

/** Zone the fill percentage falls into; used for stat-card color coding. */
function fillZone(fill: number): 'ok' | 'warn' | 'alert' {
  if (fill >= THRESHOLD_ALERT) return 'alert';
  if (fill >= THRESHOLD_WARN) return 'warn';
  return 'ok';
}

interface ChartRow {
  timestamp_seconds: number;
  /** Below 80% — green line series. ``null`` elsewhere. */
  fill_ok: number | null;
  /** 80–90% — amber line series. */
  fill_warn: number | null;
  /** At or above 90% — red line series. */
  fill_alert: number | null;
}

/**
 * Split the timeline into three null-padded series so recharts can render
 * each zone with a distinct color. A point sits in exactly one series at
 * any time; the others are null so recharts skips them. Gaps between
 * series are bridged because we duplicate the boundary sample into both
 * adjacent zones (otherwise the eye sees a visible "jump").
 */
function splitIntoZoneSeries(
  timeline: TankSummary['timeline'],
): ChartRow[] {
  return timeline.map((sample) => {
    const fill = sample.fill_percentage;
    const row: ChartRow = {
      timestamp_seconds: sample.timestamp_seconds,
      fill_ok: null,
      fill_warn: null,
      fill_alert: null,
    };
    if (fill < THRESHOLD_WARN) {
      row.fill_ok = fill;
    } else if (fill < THRESHOLD_ALERT) {
      row.fill_warn = fill;
    } else {
      row.fill_alert = fill;
    }
    return row;
  });
}

/** Custom tooltip — recharts' default shows all three series even when
 *  two are null. We only want the one with a value. */
function ChartTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;
  const valued = payload.find((p) => p.value != null);
  if (!valued) return null;
  const ts = Number(valued.payload?.timestamp_seconds ?? 0);
  const fill = Number(valued.value);
  return (
    <div className="tank-summary__tooltip">
      <div className="tank-summary__tooltip-time">{formatTimestamp(ts)}</div>
      <div className="tank-summary__tooltip-fill">{fill.toFixed(1)}%</div>
    </div>
  );
}

export function TankOverflowSummary({ summary }: TankOverflowSummaryProps) {
  const [rawOpen, setRawOpen] = useState(false);

  const { timeline, threshold_events, stats, metadata } = summary;

  const chartData = useMemo(() => splitIntoZoneSeries(timeline), [timeline]);

  const peak = stats.peak_fill_percentage ?? 0;
  const final = stats.final_fill_percentage ?? 0;
  const duration = stats.duration_seconds ?? 0;
  const framesAnalyzed = stats.frames_analyzed ?? 0;
  const framesSkipped = stats.frames_skipped ?? 0;
  const time80 = stats.time_to_80_percent_seconds ?? null;
  const time90 = stats.time_to_90_percent_seconds ?? null;

  const samplingFps =
    (metadata?.sampling_fps as number | undefined) ??
    Number((metadata?.parameters_used as Record<string, unknown>)?.sampling_fps ?? 1);
  const capacityLiters = (
    metadata?.parameters_used as Record<string, unknown> | undefined
  )?.capacity_liters as number | undefined;
  const alertThreshold = (
    metadata?.parameters_used as Record<string, unknown> | undefined
  )?.alert_threshold as number | undefined;

  return (
    <div className="tank-summary">
      {/* Stat cards */}
      <div className="tank-summary__stats">
        <StatCard
          label="Peak"
          value={`${peak.toFixed(1)}%`}
          tone={fillZone(peak)}
        />
        <StatCard
          label="Final"
          value={`${final.toFixed(1)}%`}
          tone={fillZone(final)}
        />
        <StatCard
          label="Duration"
          value={formatDuration(duration)}
          tone="neutral"
        />
        <StatCard
          label="Frames"
          value={`${framesAnalyzed}`}
          tone="neutral"
          subValue={
            framesSkipped > 0 ? (
              <span className="tank-summary__skipped">
                {framesSkipped} skipped
              </span>
            ) : (
              <span className="tank-summary__skipped tank-summary__skipped--muted">
                no skips
              </span>
            )
          }
        />
      </div>

      {/* Time to thresholds */}
      <div className="tank-summary__thresholds">
        <span className="tank-summary__threshold-label">Time to 80%:</span>
        <span className="tank-summary__threshold-value">
          {time80 !== null ? formatTimestamp(time80) : 'Not reached'}
        </span>
        <span className="tank-summary__threshold-sep">•</span>
        <span className="tank-summary__threshold-label">Time to 90%:</span>
        <span className="tank-summary__threshold-value">
          {time90 !== null ? formatTimestamp(time90) : 'Not reached'}
        </span>
      </div>

      {/* Chart */}
      <div className="tank-summary__chart">
        <h3 className="tank-summary__chart-title">Fill Level Over Time</h3>
        <ResponsiveContainer width="100%" height={340}>
          <LineChart
            data={chartData}
            margin={{ top: 16, right: 28, left: 0, bottom: 8 }}
          >
            <CartesianGrid stroke={COLOR_GRID} strokeDasharray="3 3" />
            <XAxis
              dataKey="timestamp_seconds"
              type="number"
              domain={['dataMin', 'dataMax']}
              tickFormatter={(t) => formatTimestamp(Number(t))}
              stroke={COLOR_TEXT}
            />
            <YAxis
              domain={[0, 100]}
              tickFormatter={(v) => `${v}%`}
              stroke={COLOR_TEXT}
              label={{
                value: 'Fill %',
                angle: -90,
                position: 'insideLeft',
                offset: 16,
                style: { fill: COLOR_TEXT },
              }}
            />
            <Tooltip content={<ChartTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: '0.8rem' }}
              iconType="line"
            />

            {/* Zone shading — subtle background tint per band. */}
            <ReferenceArea
              y1={0}
              y2={THRESHOLD_WARN}
              fill={COLOR_OK}
              fillOpacity={0.05}
              ifOverflow="extendDomain"
            />
            <ReferenceArea
              y1={THRESHOLD_WARN}
              y2={THRESHOLD_ALERT}
              fill={COLOR_WARN}
              fillOpacity={0.07}
              ifOverflow="extendDomain"
            />
            <ReferenceArea
              y1={THRESHOLD_ALERT}
              y2={100}
              fill={COLOR_ALERT}
              fillOpacity={0.06}
              ifOverflow="extendDomain"
            />

            {/* Threshold reference lines. */}
            <ReferenceLine
              y={THRESHOLD_WARN}
              stroke={COLOR_WARN}
              strokeDasharray="4 4"
              label={{
                value: `Warning ${THRESHOLD_WARN}%`,
                position: 'right',
                fill: COLOR_WARN,
                fontSize: 11,
              }}
            />
            <ReferenceLine
              y={THRESHOLD_ALERT}
              stroke={COLOR_ALERT}
              strokeDasharray="4 4"
              label={{
                value: `Alert ${THRESHOLD_ALERT}%`,
                position: 'right',
                fill: COLOR_ALERT,
                fontSize: 11,
              }}
            />

            {/* Threshold-crossing markers from the analysis. */}
            {threshold_events.map((event) => (
              <ReferenceLine
                key={`x-${event.threshold}-${event.crossed_at_seconds}`}
                x={event.crossed_at_seconds}
                stroke={
                  event.threshold >= THRESHOLD_ALERT ? COLOR_ALERT : COLOR_WARN
                }
                strokeDasharray="2 4"
                label={{
                  value: `${event.threshold}% at ${formatTimestamp(event.crossed_at_seconds)}`,
                  position: 'top',
                  fill:
                    event.threshold >= THRESHOLD_ALERT
                      ? COLOR_ALERT
                      : COLOR_WARN,
                  fontSize: 10,
                }}
              />
            ))}

            {/* Three-series zone coloring. */}
            <Line
              type="monotone"
              dataKey="fill_ok"
              name="< 80%"
              stroke={COLOR_OK}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls={false}
            />
            <Line
              type="monotone"
              dataKey="fill_warn"
              name="80–90%"
              stroke={COLOR_WARN}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls={false}
            />
            <Line
              type="monotone"
              dataKey="fill_alert"
              name="≥ 90%"
              stroke={COLOR_ALERT}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Model details footer */}
      <div className="tank-summary__details">
        <span>
          Model: <strong>{metadata.model_id}</strong>
          {metadata.model_version ? ` v${metadata.model_version}` : ''}
        </span>
        <span className="tank-summary__details-sep">•</span>
        <span>Sampling: {samplingFps} fps</span>
        {capacityLiters !== undefined && (
          <>
            <span className="tank-summary__details-sep">•</span>
            <span>Capacity: {capacityLiters} L</span>
          </>
        )}
        {alertThreshold !== undefined && (
          <>
            <span className="tank-summary__details-sep">•</span>
            <span>Alert threshold: {alertThreshold}%</span>
          </>
        )}
      </div>

      {/* Collapsible raw summary */}
      <div className="tank-summary__raw">
        <button
          type="button"
          className="tank-summary__raw-toggle"
          aria-expanded={rawOpen}
          onClick={() => setRawOpen((v) => !v)}
        >
          {rawOpen ? 'Hide raw summary ▴' : 'Show raw summary ▾'}
        </button>
        {rawOpen && (
          <div className="tank-summary__raw-body">
            <RawJsonSummary summary={summary as unknown as Record<string, unknown>} />
          </div>
        )}
      </div>
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: string;
  tone: 'ok' | 'warn' | 'alert' | 'neutral';
  subValue?: React.ReactNode;
}

function StatCard({ label, value, tone, subValue }: StatCardProps) {
  return (
    <div className={`tank-summary__stat tank-summary__stat--${tone}`}>
      <div className="tank-summary__stat-label">{label}</div>
      <div className="tank-summary__stat-value">{value}</div>
      {subValue !== undefined && (
        <div className="tank-summary__stat-sub">{subValue}</div>
      )}
    </div>
  );
}
