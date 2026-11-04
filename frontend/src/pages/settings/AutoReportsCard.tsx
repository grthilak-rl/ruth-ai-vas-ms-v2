import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { formatDateTime } from '../admin/format';
import { getAutoReportSettings, setAutoReportSettings } from '../../state/api/customerReports';

/**
 * Settings -> Reports: automatic per-shift customer reports.
 *
 * Off by default. When on, the server builds a report for every shift that
 * has ended (after the settle delay, so late detections are in) and lists
 * it under Recent reports as "Auto". It looks back no further than when it
 * was switched on, and does nothing while the project is stopped or ended.
 */
export function AutoReportsCard() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ['auto-report-settings'], queryFn: getAutoReportSettings });
  const [settle, setSettle] = useState('15');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (settings.data) setSettle(String(settings.data.settle_minutes));
  }, [settings.data]);

  const save = async (enabled: boolean) => {
    const minutes = Number(settle);
    if (!Number.isInteger(minutes) || minutes < 0 || minutes > 240) {
      setError('The settle delay must be a whole number of minutes, 0 to 240.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      queryClient.setQueryData(['auto-report-settings'], await setAutoReportSettings(enabled, minutes));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not save');
    } finally {
      setBusy(false);
    }
  };

  if (settings.isLoading) return <section className="admin-card">Loading…</section>;
  if (settings.isError || !settings.data) {
    return (
      <section className="admin-card">
        <p className="admin-login__error">Could not load the automatic report settings.</p>
      </section>
    );
  }
  const s = settings.data;
  return (
    <section className="admin-card branding">
      <h2 className="admin-card__title">
        Automatic shift reports: <strong>{s.enabled ? 'ON' : 'OFF'}</strong>
      </h2>
      <p className="admin-card__subtitle">
        When on, a customer report is built for every shift once it has ended, and appears under
        Analytics → Export Data → Recent reports as “Auto”. Counting: all incidents excluding
        dismissed ones; evidence gallery on. Nothing is built while the project is stopped or ended.
      </p>
      {s.enabled && s.enabled_at && (
        <p className="admin-muted">
          On since {formatDateTime(s.enabled_at)}
          {s.updated_by ? ` (${s.updated_by})` : ''}; shifts that ended before then are not built.
        </p>
      )}
      {s.idle_reason && <p className="admin-muted">Scheduler idle: {s.idle_reason}.</p>}
      {error && <p className="admin-login__error" role="alert">{error}</p>}
      <div className="branding__row">
        <label className="admin-field">
          <span className="admin-field__label">Settle delay after a shift ends (minutes)</span>
          <input
            className="admin-field__input"
            type="number"
            min={0}
            max={240}
            value={settle}
            onChange={(e) => setSettle(e.target.value)}
            disabled={busy}
          />
        </label>
        {s.enabled ? (
          <>
            <button type="button" className="admin-button" onClick={() => save(true)} disabled={busy}>
              Save delay
            </button>
            <button type="button" className="admin-button admin-button--secondary" onClick={() => save(false)} disabled={busy}>
              Turn off
            </button>
          </>
        ) : (
          <button type="button" className="admin-button" onClick={() => save(true)} disabled={busy}>
            Turn on
          </button>
        )}
      </div>
    </section>
  );
}
