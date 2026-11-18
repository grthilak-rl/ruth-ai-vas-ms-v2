import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  fetchLifecyclePreflight,
  runLifecycle,
  type LifecycleAction,
  type ProjectJob,
  type ProjectSummary,
} from '../admin/adminApi';
import { formatDateTime } from '../admin/format';
import './ProjectLifecyclePanel.css';

/**
 * Stop / Resume / End the current project (Settings -> Project).
 *
 * Every action shows its preflight first: per camera, what it is now and
 * exactly what will change, plus the site-wide effects. The plan comes from
 * the same server functions that run the action, so what is confirmed is
 * what happens. End also needs the project name typed.
 *
 * Confirming queues the action as a background job; its progress, result
 * and Retry are shown by ProjectJobProgress above this card. Only one action
 * runs at a time, so the buttons are disabled while one is running.
 *
 * Stop and Resume are safe to repeat: an interrupted one leaves the project
 * in "stopping"/"resuming" with the error shown, and running it again
 * finishes it.
 */

const STATE_LABELS: Record<string, string> = {
  active: 'Active',
  stopping: 'Stopping (incomplete)',
  stopped: 'Stopped',
  resuming: 'Resuming (incomplete)',
  ended: 'Ended',
};

const ACTION_LABELS: Record<LifecycleAction, string> = {
  stop: 'Stop project',
  resume: 'Resume project',
  end: 'End project',
};

function actionsFor(state: string): LifecycleAction[] {
  switch (state) {
    case 'active':
      return ['stop', 'end'];
    case 'stopping':
      return ['stop', 'end'];
    case 'stopped':
      return ['resume', 'end'];
    case 'resuming':
      return ['resume'];
    default:
      return [];
  }
}

export function ProjectLifecyclePanel({
  project,
  busy = false,
  onQueued,
}: {
  project: ProjectSummary | null;
  busy?: boolean;
  onQueued?: (job: ProjectJob) => void;
}) {
  const queryClient = useQueryClient();
  const [action, setAction] = useState<LifecycleAction | null>(null);

  if (!project) return null;
  const state = project.state;
  const available = actionsFor(state);

  return (
    <section className={`admin-card lifecycle lifecycle--${state}`}>
      <div className="lifecycle__header">
        <h2 className="start-project__section-title">
          {project.name}: <span className="lifecycle__state">{STATE_LABELS[state] ?? state}</span>
        </h2>
        <div className="lifecycle__buttons">
          {available.map((a) => (
            <button
              key={a}
              type="button"
              className={`admin-button ${a === 'end' ? 'admin-button--danger' : a === 'stop' ? 'admin-button--secondary' : ''}`}
              onClick={() => setAction(a)}
              disabled={action !== null || busy}
              title={busy ? 'Another project action is running' : undefined}
            >
              {(state === 'stopping' && a === 'stop') || (state === 'resuming' && a === 'resume')
                ? `Finish: ${ACTION_LABELS[a].toLowerCase()}`
                : `${ACTION_LABELS[a]}…`}
            </button>
          ))}
        </div>
      </div>

      <p className="admin-muted">
        {state === 'active' &&
          'Cameras, recording and inference run as configured. Stop turns the site off without losing anything; Resume brings the cameras back exactly as they were. End makes the project past, so the next one can start.'}
        {state === 'stopped' &&
          `Stopped ${project.stopped_at ? formatDateTime(project.stopped_at) : ''}${project.stopped_by ? ` by ${project.stopped_by}` : ''}. Cameras are disabled, inference is off and footage deletion is paused (Resume leaves the pause on; only Settings → System lifts it). All data stays readable.`}
        {state === 'ended' &&
          `Ended ${project.ended_at ? formatDateTime(project.ended_at) : ''}${project.ended_by ? ` by ${project.ended_by}` : ''}. Its data stays viewable from the project list; start the next project when ready.`}
        {(state === 'stopping' || state === 'resuming') &&
          'The last attempt did not finish. Running it again is safe and completes it.'}
      </p>
      {project.lifecycle_error && (
        <p className="admin-login__error" role="alert">Last attempt: {project.lifecycle_error}</p>
      )}

      {action && (
        <Preflight
          project={project}
          action={action}
          onCancel={() => setAction(null)}
          onDone={(job) => {
            setAction(null);
            onQueued?.(job);
            queryClient.invalidateQueries({ queryKey: ['admin', 'projects'] });
          }}
        />
      )}
    </section>
  );
}

function Preflight({
  project,
  action,
  onCancel,
  onDone,
}: {
  project: ProjectSummary;
  action: LifecycleAction;
  onCancel: () => void;
  onDone: (job: ProjectJob) => void;
}) {
  const plan = useQuery({
    queryKey: ['admin', 'projects', 'lifecycle', action],
    queryFn: () => fetchLifecyclePreflight(action),
    retry: false,
    refetchInterval: 15_000,
  });
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nameOk = action !== 'end' || typed === project.name;
  const changing = plan.data?.cameras.filter((c) => c.vas_change || c.live_session).length ?? 0;

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await runLifecycle(action, typed));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'The action did not run');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="lifecycle__preflight">
      <h3>{ACTION_LABELS[action]}: what will change</h3>
      {plan.isPending && <p className="admin-muted">Checking every camera…</p>}
      {plan.isError && (
        <p className="admin-login__error">
          Could not build the plan: {plan.error instanceof Error ? plan.error.message : 'error'}
        </p>
      )}
      {plan.data && (
        <>
          {!plan.data.allowed && (
            <p className="admin-login__error">{plan.data.blocked_reason}</p>
          )}
          <ul className="lifecycle__effects">
            {plan.data.effects.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
          <p className="admin-muted">
            {changing} of {plan.data.cameras.length} cameras change. Highlighted rows change.
          </p>
          <div className="lifecycle__table-wrap">
            <table className="lifecycle__table">
              <thead>
                <tr>
                  <th>Camera</th>
                  <th>In VAS now</th>
                  <th>Inference intent</th>
                  <th>What will happen</th>
                </tr>
              </thead>
              <tbody>
                {plan.data.cameras.map((c) => (
                  <tr key={c.vas_device_id} className={c.vas_change || c.live_session ? 'lifecycle__row--change' : ''}>
                    <td>{c.name}</td>
                    <td>{c.vas_enabled_now ? 'Enabled' : 'Disabled'}</td>
                    <td>
                      {c.intent ? `${c.intent} (${c.intent_models} model${c.intent_models === 1 ? '' : 's'})` : '—'}
                      {c.live_session && ' · running'}
                    </td>
                    <td>
                      <ul className="lifecycle__actions">
                        {c.actions.map((a) => (
                          <li key={a}>{a}</li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {action === 'end' && (
            <label className="admin-field lifecycle__confirm">
              <span className="admin-field__label">
                Ending is permanent: the project cannot be resumed. Type <strong>{project.name}</strong> to confirm.
              </span>
              <input
                className="admin-field__input"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                autoComplete="off"
              />
            </label>
          )}
          {error && <p className="admin-login__error" role="alert">{error}</p>}
          <div className="lifecycle__buttons">
            <button
              type="button"
              className={`admin-button ${action === 'end' ? 'admin-button--danger' : ''}`}
              onClick={run}
              disabled={busy || !plan.data.allowed || !nameOk}
            >
              {busy ? 'Queueing…' : `Confirm: ${ACTION_LABELS[action].toLowerCase()}`}
            </button>
            <button type="button" className="admin-button admin-button--secondary" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
          </div>
        </>
      )}
    </div>
  );
}
