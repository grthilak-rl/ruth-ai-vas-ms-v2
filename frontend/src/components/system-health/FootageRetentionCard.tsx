import { useCallback, useEffect, useState } from 'react';
import { apiGet } from '../../state/api/client';
import { adminFetch, ADMIN_API_PREFIX } from '../../pages/admin/adminApi';
import { useAdminSession } from '../../pages/admin/useAdminSession';
import { InlineAdminSignIn } from '../../pages/settings/InlineAdminSignIn';
import './FootageRetentionCard.css';

/**
 * Footage deletion, as VAS has it.
 *
 * VAS is the single source of truth; this card reads it on every load and
 * forwards changes to it. Footage (recordings, snapshots, bookmarks) is
 * deleted only by VAS's retention cleanup, and only while deletion is ON
 * and not paused. The default is OFF. When VAS cannot be read the card says
 * so instead of guessing: an unknown state must never read as "OFF".
 *
 * Changing it needs the admin sign-in. Turning deletion ON asks for the
 * number of days and a typed confirmation, because it is the one action
 * here that destroys footage.
 */

interface FootageRetention {
  footage_deletion: 'off' | 'paused' | 'on';
  cleanup_enabled: boolean;
  retention_paused: boolean;
  hot_retention_days: number | null;
  hot_retention_days_set: boolean;
  snapshot_retention_days: number | null;
  bookmark_retention_days: number | null;
  disk_alert_enabled: boolean | null;
  disk_usage_percent: number | null;
  disk_free_bytes: number | null;
  disk_alert_level: 'ok' | 'warning' | 'critical' | null;
  disk_warning_threshold: number | null;
  disk_critical_threshold: number | null;
}

const PATH = '/api/v1/storage/footage-retention';
const ADMIN_PATH = `${ADMIN_API_PREFIX}/footage-retention`;
const REFRESH_MS = 60_000;

function terabytes(bytes: number | null): string {
  if (bytes == null) return '—';
  return bytes >= 1e12 ? `${(bytes / 1e12).toFixed(1)} TB` : `${Math.round(bytes / 1e9)} GB`;
}

export function FootageRetentionCard() {
  const [state, setState] = useState<FootageRetention | null>(null);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(() => {
    apiGet<FootageRetention>(PATH)
      .then((s) => {
        setState(s);
        setLoadError(false);
      })
      .catch(() => setLoadError(true));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => clearInterval(t);
  }, [load]);

  if (!state) {
    return (
      <section className={`footage-retention ${loadError ? 'footage-retention--unknown' : ''}`}>
        <div className="footage-retention__headline">
          <span className="footage-retention__label">Footage deletion</span>
          <span className="footage-retention__summary">
            {loadError ? 'UNKNOWN: could not read the storage settings from VAS.' : 'Loading…'}
          </span>
        </div>
      </section>
    );
  }

  const mode = state.footage_deletion;
  const headline = mode === 'on' ? 'ON' : mode === 'paused' ? 'PAUSED' : 'OFF';
  return (
    <section className={`footage-retention footage-retention--${mode}`} aria-live="polite">
      <div className="footage-retention__headline">
        <span className="footage-retention__label">
          Footage deletion: <strong className="footage-retention__state">{headline}</strong>
        </span>
        {loadError && (
          <span className="footage-retention__stale">Last known state; VAS not reachable now</span>
        )}
      </div>
      <p className="footage-retention__summary">
        {mode === 'off' &&
          'Recordings, snapshots and bookmarks are kept indefinitely. Nothing is deleted automatically.'}
        {mode === 'paused' &&
          'Paused (project stopped or ended). Nothing is deleted, whatever the retention settings say.'}
        {mode === 'on' &&
          `Recordings older than ${state.hot_retention_days} days, snapshots older than ` +
            `${state.snapshot_retention_days} days and bookmarks older than ` +
            `${state.bookmark_retention_days} days are permanently deleted.`}
      </p>

      <DiskLine state={state} />
      <Controls state={state} onChanged={setState} />
    </section>
  );
}

function DiskLine({ state }: { state: FootageRetention }) {
  if (state.disk_usage_percent == null) return null;
  const level = state.disk_alert_level;
  return (
    <p className={`footage-retention__disk ${level ? `footage-retention__disk--${level}` : ''}`}>
      Recordings volume: {state.disk_usage_percent}% used, {terabytes(state.disk_free_bytes)} free
      {level === 'warning' && ` (warning: above ${state.disk_warning_threshold}%)`}
      {level === 'critical' && ` (critical: above ${state.disk_critical_threshold}%)`}
      {!state.disk_alert_enabled && ' (disk alert off)'}
    </p>
  );
}

function Controls({
  state,
  onChanged,
}: {
  state: FootageRetention;
  onChanged: (s: FootageRetention) => void;
}) {
  const { isSignedIn } = useAdminSession();
  const [open, setOpen] = useState(false);
  const [enabling, setEnabling] = useState(false);
  const [days, setDays] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = async (body: Record<string, unknown>) => {
    setBusy(true);
    setError(null);
    try {
      onChanged(await adminFetch<FootageRetention>(ADMIN_PATH, { method: 'PUT', body: JSON.stringify(body) }));
      setEnabling(false);
      setConfirm('');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'The change was not applied');
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button type="button" className="footage-retention__link" onClick={() => setOpen(true)}>
        Change…
      </button>
    );
  }
  if (!isSignedIn) {
    return <InlineAdminSignIn capability="change footage deletion" />;
  }

  const daysValue = Number(days);
  const daysOk = Number.isInteger(daysValue) && daysValue >= 1 && daysValue <= 365;
  return (
    <div className="footage-retention__controls">
      {error && <p className="footage-retention__error" role="alert">{error}</p>}
      <div className="footage-retention__buttons">
        {state.retention_paused ? (
          <button type="button" onClick={() => change({ retention_paused: false })} disabled={busy}>
            Remove pause
          </button>
        ) : (
          <button type="button" onClick={() => change({ retention_paused: true })} disabled={busy}>
            Pause all deletion
          </button>
        )}
        {state.cleanup_enabled ? (
          <button type="button" onClick={() => change({ cleanup_enabled: false })} disabled={busy}>
            Turn deletion off
          </button>
        ) : (
          !enabling && (
            <button
              type="button"
              className="footage-retention__danger"
              onClick={() => setEnabling(true)}
              disabled={busy}
            >
              Turn deletion on…
            </button>
          )
        )}
      </div>

      {enabling && (
        <form
          className="footage-retention__enable"
          onSubmit={(e) => {
            e.preventDefault();
            if (daysOk && confirm === 'DELETE') {
              change({ cleanup_enabled: true, hot_retention_days: daysValue });
            }
          }}
        >
          <p>
            Turning deletion on <strong>permanently deletes</strong> recordings older than the
            number of days below (checked hourly), and snapshots and bookmarks older than{' '}
            {state.snapshot_retention_days} / {state.bookmark_retention_days} days (checked
            daily). Deleted footage cannot be recovered.
            {state.retention_paused && ' While the pause is on, nothing is deleted.'}
          </p>
          <label>
            Keep recordings for (days){' '}
            <input type="number" min={1} max={365} value={days} onChange={(e) => setDays(e.target.value)} />
          </label>
          <label>
            Type DELETE to confirm{' '}
            <input value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
          </label>
          <div className="footage-retention__buttons">
            <button
              type="submit"
              className="footage-retention__danger"
              disabled={busy || !daysOk || confirm !== 'DELETE'}
            >
              Turn deletion on
            </button>
            <button type="button" onClick={() => setEnabling(false)} disabled={busy}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
