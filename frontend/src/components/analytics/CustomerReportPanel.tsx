import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { setSessionExpiredHandler } from '../../pages/admin/adminApi';
import { notifyAdminSessionChanged, useAdminSession } from '../../pages/admin/useAdminSession';
import { InlineAdminSignIn } from '../../pages/settings/InlineAdminSignIn';
import {
  createCustomerReport,
  downloadCustomerReport,
  getCustomerReport,
  getReportDefaults,
  listCustomerReports,
  type CustomerReportDefaults,
  type CustomerReportJob,
  type ReportMode,
  type ReportPreset,
} from '../../state/api/customerReports';
import { formatBytes } from '../../state/api/violationExports';
import './CustomerReportPanel.css';

/**
 * Analytics → Export Data → Customer report.
 *
 * Builds the customer-facing PDF as a background job (reports are kept on
 * the server for re-download), shows its progress, downloads it when ready,
 * and lists recent reports so the same one can be sent again.
 *
 * Periods follow the site's shift day (from the backend's defaults): a daily
 * report for 3 Nov runs 07:00 3 Nov → 07:00 4 Nov when the first shift starts
 * at 07:00. Custom periods run midnight to midnight.
 *
 * Admin-only, signed in inline: the PDF carries identifiable worker images.
 */

const POLL_MS = 1000;
const MODE_LABELS: Record<ReportMode, string> = {
  all: 'All incidents',
  verified: 'Verified only',
};
const PRESET_LABELS: Record<ReportPreset, string> = {
  daily: 'Daily',
  weekly: 'Weekly',
  custom: 'Custom',
};

/** YYYY-MM-DD arithmetic without time zones getting involved. */
function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

function daySpan(a: string, b: string): number {
  return Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000) + 1;
}

function formatDay(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  });
}

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function CustomerReportPanel() {
  const { isSignedIn } = useAdminSession();
  const [expired, setExpired] = useState(false);

  // This page is not inside Settings, so without a handler a 401 would
  // redirect to the login page and lose the form. Flip to signed-out in place.
  useEffect(() => {
    setSessionExpiredHandler(() => {
      setExpired(true);
      notifyAdminSessionChanged();
    });
    return () => setSessionExpiredHandler(null);
  }, []);

  if (!isSignedIn) {
    return (
      <section className="customer-report">
        <p className="customer-report__intro">
          A customer-ready PDF: executive summary, areas, trends, evidence images,
          recommendations and the incident list. It includes images of workers, so it needs an
          admin sign-in.
        </p>
        <InlineAdminSignIn capability="generate customer reports" expired={expired} />
      </section>
    );
  }
  return <SignedInPanel />;
}

function SignedInPanel() {
  const defaults = useQuery({ queryKey: ['customer-report-defaults'], queryFn: getReportDefaults });
  if (defaults.isLoading) {
    return <section className="customer-report">Loading report options…</section>;
  }
  if (defaults.isError || !defaults.data) {
    return (
      <section className="customer-report">
        <div className="customer-report__message customer-report__message--error">
          Could not load report options: {errorText(defaults.error, 'unknown error')}
        </div>
      </section>
    );
  }
  return <ReportForm defaults={defaults.data} />;
}

function ReportForm({ defaults }: { defaults: CustomerReportDefaults }) {
  const queryClient = useQueryClient();
  const lastDay = defaults.last_complete_day;
  // The shift day in progress may be reported too; it is marked incomplete.
  const maxDay = addDays(lastDay, 1);
  const minDay = defaults.project_started_on ?? undefined;

  const [preset, setPreset] = useState<ReportPreset>('daily');
  const [day, setDay] = useState(lastDay);
  const [weekEnd, setWeekEnd] = useState(lastDay);
  const [start, setStart] = useState(addDays(lastDay, -29));
  const [end, setEnd] = useState(lastDay);
  const [mode, setMode] = useState<ReportMode>('all');
  const [gallery, setGallery] = useState(true);
  const [gallerySize, setGallerySize] = useState(defaults.default_gallery_size);

  const [jobId, setJobId] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const downloaded = useRef<string | null>(null);

  const ds = defaults.day_start;
  const periodWindow = useMemo(() => {
    if (preset === 'daily') {
      return `${formatDay(day)} ${ds} → ${formatDay(addDays(day, 1))} ${ds}`;
    }
    if (preset === 'weekly') {
      return `${formatDay(addDays(weekEnd, -6))} ${ds} → ${formatDay(addDays(weekEnd, 1))} ${ds}`;
    }
    return `${formatDay(start)} 00:00 → ${formatDay(addDays(end, 1))} 00:00`;
  }, [preset, day, weekEnd, start, end, ds]);

  const periodProblem = useMemo(() => {
    if (preset === 'custom') {
      if (!start || !end) return 'Pick a start and an end date.';
      if (end < start) return 'The end date is before the start date.';
      if (daySpan(start, end) > defaults.max_custom_days) {
        return `A custom period can be at most ${defaults.max_custom_days} days.`;
      }
    } else if (!(preset === 'daily' ? day : weekEnd)) {
      return 'Pick a day.';
    }
    return null;
  }, [preset, day, weekEnd, start, end, defaults.max_custom_days]);

  const inProgress =
    (preset === 'daily' && day === maxDay) ||
    (preset === 'weekly' && weekEnd === maxDay) ||
    (preset === 'custom' && end >= maxDay);

  const job = useQuery({
    queryKey: ['customer-report', jobId],
    queryFn: () => getCustomerReport(jobId as string),
    enabled: jobId !== null,
    refetchInterval: (query) => (query.state.data?.status === 'building' ? POLL_MS : false),
  });

  const recent = useQuery({
    queryKey: ['customer-reports'],
    queryFn: () => listCustomerReports(20),
    refetchInterval: (query) =>
      query.state.data?.items.some((r) => r.status === 'building') ? 3000 : false,
  });

  // Download once when the job we started finishes, then refresh the list.
  const current = job.data;
  useEffect(() => {
    if (!current || current.status !== 'ready' || downloaded.current === current.id) return;
    downloaded.current = current.id;
    queryClient.invalidateQueries({ queryKey: ['customer-reports'] });
    downloadCustomerReport(current).catch((e: unknown) =>
      setDownloadError(errorText(e, 'Download failed'))
    );
  }, [current, queryClient]);

  useEffect(() => {
    if (current?.status === 'failed') {
      queryClient.invalidateQueries({ queryKey: ['customer-reports'] });
    }
  }, [current?.status, queryClient]);

  const building = current?.status === 'building';

  const generate = async () => {
    setStarting(true);
    setStartError(null);
    setDownloadError(null);
    try {
      const created = await createCustomerReport({
        format: 'pdf',
        preset,
        day: preset === 'daily' ? day : preset === 'weekly' ? weekEnd : null,
        start: preset === 'custom' ? start : null,
        end: preset === 'custom' ? end : null,
        mode,
        gallery,
        gallery_size: gallerySize,
      });
      queryClient.setQueryData(['customer-report', created.id], created);
      setJobId(created.id);
      queryClient.invalidateQueries({ queryKey: ['customer-reports'] });
    } catch (e: unknown) {
      setStartError(errorText(e, 'Could not start the report'));
    } finally {
      setStarting(false);
    }
  };

  return (
    <section className="customer-report">
      <p className="customer-report__intro">
        A customer-ready PDF: executive summary, areas at a glance, trends, where and when,
        evidence images, recommendations and the incident list. Counts incidents (repeated
        detections grouped), not raw detections.
      </p>

      <div className="customer-report__grid">
        <div className="customer-report__card">
          <h2 className="customer-report__card-title">Period</h2>
          <div className="customer-report__segments" role="radiogroup" aria-label="Period type">
            {(Object.keys(PRESET_LABELS) as ReportPreset[]).map((p) => (
              <button
                key={p}
                type="button"
                role="radio"
                aria-checked={preset === p}
                className={`customer-report__segment ${preset === p ? 'customer-report__segment--active' : ''}`}
                onClick={() => setPreset(p)}
                disabled={building}
              >
                {PRESET_LABELS[p]}
              </button>
            ))}
          </div>

          {preset === 'daily' && (
            <label className="customer-report__field">
              <span>Shift day</span>
              <input type="date" value={day} min={minDay} max={maxDay}
                onChange={(e) => setDay(e.target.value)} disabled={building} />
            </label>
          )}
          {preset === 'weekly' && (
            <label className="customer-report__field">
              <span>Last day of the week</span>
              <input type="date" value={weekEnd} min={minDay} max={maxDay}
                onChange={(e) => setWeekEnd(e.target.value)} disabled={building} />
            </label>
          )}
          {preset === 'custom' && (
            <div className="customer-report__range">
              <label className="customer-report__field">
                <span>From</span>
                <input type="date" value={start} max={maxDay}
                  onChange={(e) => setStart(e.target.value)} disabled={building} />
              </label>
              <label className="customer-report__field">
                <span>To (included)</span>
                <input type="date" value={end} max={maxDay}
                  onChange={(e) => setEnd(e.target.value)} disabled={building} />
              </label>
            </div>
          )}

          <p className="customer-report__window">
            {periodWindow} <span className="customer-report__muted">({defaults.timezone})</span>
          </p>
          {preset !== 'custom' && ds !== '00:00' && (
            <p className="customer-report__hint">
              Days are shift days: each starts with the first shift at {ds}.
              {preset === 'daily' ? ' Compared with the 7-day average before it.' : ' Compared with the 7 days before.'}
            </p>
          )}
          {preset === 'custom' && (
            <p className="customer-report__hint">
              Midnight to midnight, compared with the same number of days before it. Up to{' '}
              {defaults.max_custom_days} days.
            </p>
          )}
          {inProgress && !periodProblem && (
            <p className="customer-report__hint">
              This period has not ended yet; the report will say so and count what has happened so far.
            </p>
          )}
        </div>

        <div className="customer-report__card">
          <h2 className="customer-report__card-title">Options</h2>
          <fieldset className="customer-report__fieldset" disabled={building}>
            <legend>Counting</legend>
            <label className="customer-report__choice">
              <input type="radio" name="report-mode" checked={mode === 'all'}
                onChange={() => setMode('all')} />
              <span>
                <strong>All incidents</strong>, excluding those dismissed as false alarms
                <small>Recommended: operators dismiss the obvious false alarms only.</small>
              </span>
            </label>
            <label className="customer-report__choice">
              <input type="radio" name="report-mode" checked={mode === 'verified'}
                onChange={() => setMode('verified')} />
              <span>
                <strong>Verified only</strong>: incidents an operator reviewed or resolved
                <small>Labelled as such on every page of the report.</small>
              </span>
            </label>
          </fieldset>

          <fieldset className="customer-report__fieldset" disabled={building}>
            <legend>Evidence gallery</legend>
            <label className="customer-report__choice">
              <input type="checkbox" checked={gallery} onChange={(e) => setGallery(e.target.checked)} />
              <span>
                Include images of the most significant incidents
                <small>Cropped frames the AI analysed. They show workers.</small>
              </span>
            </label>
            <label className="customer-report__field customer-report__field--inline">
              <span>Images</span>
              <select value={gallerySize} disabled={!gallery}
                onChange={(e) => setGallerySize(Number(e.target.value))}>
                {defaults.gallery_sizes.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </label>
          </fieldset>

          <p className="customer-report__hint">Format: PDF.</p>
        </div>
      </div>

      {periodProblem && (
        <div className="customer-report__message customer-report__message--error">{periodProblem}</div>
      )}
      {startError && (
        <div className="customer-report__message customer-report__message--error">{startError}</div>
      )}

      {current && <JobStatus job={current} downloadError={downloadError}
        onDownload={() => downloadCustomerReport(current).catch((e: unknown) =>
          setDownloadError(errorText(e, 'Download failed')))} />}

      <div className="customer-report__actions">
        <button type="button" className="export-page__btn export-page__btn--primary"
          onClick={generate} disabled={starting || building || periodProblem !== null}>
          {starting ? 'Starting…' : building ? 'Generating…' : 'Generate report'}
        </button>
      </div>

      <RecentReports
        items={recent.data?.items ?? []}
        loading={recent.isLoading}
        error={recent.isError ? errorText(recent.error, 'Could not load recent reports') : null}
        retentionDays={defaults.retention_days}
      />
    </section>
  );
}

function JobStatus({
  job,
  downloadError,
  onDownload,
}: {
  job: CustomerReportJob;
  downloadError: string | null;
  onDownload: () => void;
}) {
  if (job.status === 'building') {
    const pct = job.total ? Math.round((100 * job.done) / job.total) : 0;
    return (
      <div className="customer-report__progress" role="status" aria-live="polite">
        <div className="customer-report__progress-label">
          {job.stage ?? 'Working'}… <span className="customer-report__muted">{job.period_label}</span>
        </div>
        <div className="customer-report__bar" aria-hidden="true">
          <div className="customer-report__bar-fill" style={{ width: `${Math.max(pct, 5)}%` }} />
        </div>
      </div>
    );
  }
  if (job.status === 'failed') {
    return (
      <div className="customer-report__message customer-report__message--error">
        The report could not be built: {job.error ?? 'unknown error'}
      </div>
    );
  }
  if (job.status === 'ready') {
    return (
      <div className="customer-report__message customer-report__message--success">
        Report ready: {job.filename} ({formatBytes(job.size_bytes)}, {job.incidents ?? 0} incidents).
        Your download should start automatically.{' '}
        <button type="button" className="customer-report__link" onClick={onDownload}>
          Download again
        </button>
        {downloadError && <div>Download failed: {downloadError}</div>}
      </div>
    );
  }
  return null;
}

function RecentReports({
  items,
  loading,
  error,
  retentionDays,
}: {
  items: CustomerReportJob[];
  loading: boolean;
  error: string | null;
  retentionDays: number;
}) {
  const [rowError, setRowError] = useState<string | null>(null);
  return (
    <div className="customer-report__recent">
      <h2 className="customer-report__card-title">Recent reports</h2>
      <p className="customer-report__hint">
        Reports stay downloadable for {retentionDays} days, so the same report can be sent again.
      </p>
      {loading && <p className="customer-report__muted">Loading…</p>}
      {error && <div className="customer-report__message customer-report__message--error">{error}</div>}
      {rowError && <div className="customer-report__message customer-report__message--error">{rowError}</div>}
      {!loading && !error && items.length === 0 && (
        <p className="customer-report__muted">No reports generated yet.</p>
      )}
      {items.length > 0 && (
        <div className="customer-report__table-wrap">
          <table className="customer-report__table">
            <thead>
              <tr>
                <th>Generated</th>
                <th>By</th>
                <th>Period</th>
                <th>Counting</th>
                <th className="customer-report__num">Incidents</th>
                <th className="customer-report__num">Size</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id}>
                  <td>{formatWhen(r.created_at)}</td>
                  <td>{r.created_by ?? '—'}</td>
                  <td>
                    {r.period_label}
                    <span className="customer-report__muted"> · {PRESET_LABELS[r.preset] ?? r.preset}</span>
                  </td>
                  <td>{MODE_LABELS[r.mode] ?? r.mode}</td>
                  <td className="customer-report__num">{r.incidents ?? '—'}</td>
                  <td className="customer-report__num">{formatBytes(r.size_bytes)}</td>
                  <td>
                    {r.status === 'ready' && (
                      <button type="button" className="customer-report__link"
                        title={r.expires_at ? `Available until ${formatWhen(r.expires_at)}` : undefined}
                        onClick={() => {
                          setRowError(null);
                          downloadCustomerReport(r).catch((e: unknown) =>
                            setRowError(errorText(e, 'Download failed')));
                        }}>
                        Download
                      </button>
                    )}
                    {r.status === 'building' && <span className="customer-report__muted">{r.stage ?? 'Building'}…</span>}
                    {r.status === 'failed' && <span className="customer-report__failed" title={r.error ?? ''}>Failed</span>}
                    {r.status === 'expired' && <span className="customer-report__muted">Expired</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
