import { useEffect, useRef } from 'react';
import { AdminApiError, isJobActive, type ProjectJob } from '../admin/adminApi';
import './ProjectJobProgress.css';

/**
 * A project action running in the background: its stages, the one running
 * now (with e.g. "DEMO-CAMERA2 (2/3)"), and how it ended. A failed or
 * interrupted action offers Retry, which continues from the recorded stage
 * (a Start never backs up twice or creates the project twice).
 */

const VERB: Record<ProjectJob['action'], string> = {
  start: 'Starting',
  stop: 'Stopping',
  end: 'Ending',
  resume: 'Resuming',
  cameras: 'Changing the cameras of',
};

const DONE: Record<ProjectJob['action'], (name: string) => string> = {
  start: (n) => `${n} is now the current project`,
  stop: (n) => `${n} is stopped`,
  end: (n) => `${n} has ended`,
  resume: (n) => `${n} is running again`,
  cameras: (n) => `The cameras of ${n} are changed`,
};

const MARK: Record<string, string> = {
  done: '✓',
  running: '●',
  failed: '✕',
  interrupted: '!',
  pending: '○',
};

function heading(job: ProjectJob): string {
  const name = job.project_name ?? 'the project';
  switch (job.state) {
    case 'queued':
    case 'running':
      return `${VERB[job.action]} ${name}…`;
    case 'succeeded':
      return DONE[job.action](name);
    case 'interrupted':
      return `${VERB[job.action]} ${name} was interrupted`;
    default:
      return `${VERB[job.action]} ${name} did not finish`;
  }
}

export function ProjectJobProgress({
  job,
  onRetry,
  retrying,
  retryError,
  onDismiss,
}: {
  job: ProjectJob;
  onRetry: () => void;
  retrying: boolean;
  retryError?: unknown;
  onDismiss: () => void;
}) {
  const active = isJobActive(job);
  // A new action appears at the top of the tab, often far above the button
  // that queued it (the Start form's camera list is long): bring it into view.
  const card = useRef<HTMLElement>(null);
  useEffect(() => {
    // Instant, not smooth: the form re-renders as the job is queued, and a
    // smooth scroll in progress is cancelled by that layout change.
    card.current?.scrollIntoView?.({ block: 'start' });
  }, [job.id]);
  const changed = job.cameras.filter((c) => c.vas_change).length;
  const failedStage = job.stages.find((s) => s.status === 'failed' || s.status === 'interrupted');
  const cameraErrors = job.errors.filter((e) => e !== job.error_message);

  return (
    <section
      ref={card}
      className={`admin-card project-job project-job--${job.state}`}
      role="status"
      aria-live="polite"
      aria-busy={active}
    >
      <h2 className="project-job__title">{heading(job)}</h2>

      <ol className="project-job__stages">
        {job.stages.map((s) => (
          <li key={s.key} className={`project-job__stage project-job__stage--${s.status}`}>
            <span className="project-job__mark" aria-hidden="true">
              {MARK[s.status] ?? '○'}
            </span>
            <span className="project-job__label">{s.label}</span>
            {(s.status === 'running' || s.status === 'failed' || s.status === 'interrupted') &&
              job.stage === s.key &&
              job.stage_detail && <span className="project-job__detail">{job.stage_detail}</span>}
            <span className="visually-hidden">: {s.status}</span>
          </li>
        ))}
      </ol>

      {active && (
        <p className="admin-muted">
          Runs in the background: you can leave this page; the result stays here.
        </p>
      )}

      {job.state === 'succeeded' && (
        <p>
          {job.action === 'start' &&
            'New detections, reports and exports are tagged with it. Nothing was archived or deleted. '}
          {changed > 0 && `${changed} camera${changed === 1 ? '' : 's'} changed in VAS. `}
          {job.retention_paused !== null &&
            `Footage deletion pause: ${job.retention_paused ? 'on' : 'off'} (only Settings → System changes it).`}
        </p>
      )}

      {(job.state === 'failed' || job.state === 'interrupted') && (
        <>
          {job.error_message && (
            <p className="admin-login__error" role="alert">
              {job.error_message}
            </p>
          )}
          {cameraErrors.length > 0 && (
            <ul className="project-job__errors">
              {cameraErrors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
        </>
      )}

      {retryError != null && (
        <p className="admin-login__error" role="alert">
          {retryError instanceof AdminApiError ? retryError.message : 'Retry did not start'}
        </p>
      )}

      {!active && (
        <div className="project-job__buttons">
          {job.can_retry && (
            <button type="button" className="admin-button" onClick={onRetry} disabled={retrying}>
              {retrying ? 'Retrying…' : failedStage ? `Retry from “${failedStage.label}”` : 'Retry'}
            </button>
          )}
          <button type="button" className="admin-button admin-button--secondary" onClick={onDismiss}>
            Dismiss
          </button>
        </div>
      )}
      {job.attempts > 1 && <p className="admin-muted project-job__attempts">Attempt {job.attempts}</p>}
    </section>
  );
}
