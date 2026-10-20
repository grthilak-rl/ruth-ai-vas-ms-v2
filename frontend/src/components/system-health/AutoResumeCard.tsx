import { useEffect, useState } from 'react';
import { apiGet } from '../../state/api/client';
import './AutoResumeCard.css';

/**
 * Auto-resume activity, and cameras the reconciler has given up on.
 *
 * BL-11 A. Inference can stop without anyone choosing it — a backend
 * restart mid-handover, VAS dropping a stream, a crash. The reconciler
 * puts it back; this is where an operator finds out that it had to.
 *
 * The parked list is the part that needs a human. A parked camera has
 * live video and working dependencies and *still* will not start, which
 * is a real fault rather than a blip, and nothing will fix it on its own.
 */

interface ParkedCamera {
  camera: string;
  device_id: string;
  since: string | null;
  consecutive_failures: number;
  last_error: string | null;
  retry_due_at: string | null;
}

interface AutoResumeStatus {
  enabled: boolean;
  last_run_at: string | null;
  resumes_last_24h: { camera: string; at: string }[];
  resume_count_24h: number;
  parked: ParkedCamera[];
  dependency_error: string | null;
}

const REFRESH_MS = 30000;

function when(iso: string | null): string {
  if (!iso) return 'unknown';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, {
        day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
      });
}

export function AutoResumeCard() {
  const [status, setStatus] = useState<AutoResumeStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      apiGet<AutoResumeStatus>('/api/v1/health/auto-resume')
        .then((s) => !cancelled && setStatus(s as AutoResumeStatus))
        .catch(() => undefined);
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  if (!status || !status.enabled) return null;

  const hasParked = status.parked.length > 0;
  // A shared-dependency outage is one system problem, not one per camera,
  // so it gets a single line rather than twelve parked entries.
  const tone = hasParked || status.dependency_error ? 'warn' : 'ok';

  return (
    <section className={`auto-resume auto-resume--${tone}`} aria-live="polite">
      <div className="auto-resume__headline">
        <span className="auto-resume__label">Auto-resume</span>
        <span className="auto-resume__summary">
          {status.resume_count_24h === 0
            ? 'nothing needed restarting in 24 h'
            : `${status.resume_count_24h} restored in 24 h`}
        </span>
      </div>

      {status.dependency_error && (
        <p className="auto-resume__dependency" role="alert">
          Paused: {status.dependency_error}. No cameras were marked failed —
          this is one outage, not a per-camera fault.
        </p>
      )}

      {hasParked && (
        <div className="auto-resume__parked" role="alert">
          <p className="auto-resume__parked-title">
            {status.parked.length === 1
              ? 'This camera could not be restarted and needs attention:'
              : `${status.parked.length} cameras could not be restarted and need attention:`}
          </p>
          <ul className="auto-resume__list">
            {status.parked.map((p) => (
              <li key={p.device_id}>
                <span className="auto-resume__camera">{p.camera}</span>
                <span className="auto-resume__detail">
                  {' — failing since '}{when(p.since)}
                  {p.retry_due_at && `, next try ${when(p.retry_due_at)}`}
                </span>
                {p.last_error && (
                  <div className="auto-resume__error">{p.last_error}</div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {status.resume_count_24h > 0 && (
        <ul className="auto-resume__recent">
          {status.resumes_last_24h.slice(0, 5).map((r) => (
            <li key={`${r.camera}-${r.at}`}>
              {r.camera} restored {when(r.at)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
