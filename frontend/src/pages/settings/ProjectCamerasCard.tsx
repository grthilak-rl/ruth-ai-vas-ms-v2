import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AdminApiError,
  changeProjectCameras,
  fetchCamerasPreflight,
  type ProjectJob,
  type ProjectSummary,
} from '../admin/adminApi';
import { formatDateTime } from '../admin/format';
import './ProjectCamerasCard.css';

/**
 * Settings -> Project: "Cameras in this project".
 *
 * Lists the current project's cameras (since when), and adds or removes
 * cameras mid-project. Ticking/unticking shows the same per-camera preview
 * as the other project actions; confirming queues a "Change cameras" job
 * (progress, 409 and Retry in the card above). Removed cameras leave the
 * project from now: their data stays, analytics count them for the time
 * they were in, their inference intent is kept and their VAS placement is
 * never touched. Only while the project is active.
 */
export function ProjectCamerasCard({
  project,
  busy,
  onQueued,
}: {
  project: ProjectSummary;
  busy: boolean;
  onQueued: (job: ProjectJob) => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [add, setAdd] = useState<string[]>([]);
  const [remove, setRemove] = useState<string[]>([]);

  const plan = useQuery({
    queryKey: ['admin', 'projects', 'cameras-preflight', project.id, add, remove],
    queryFn: () => fetchCamerasPreflight(add, remove),
    retry: false,
    placeholderData: (prev) => prev,
  });

  const apply = useMutation({
    mutationFn: () => changeProjectCameras({ add, remove }),
    onSuccess: (job) => {
      onQueued(job);
      setEditing(false);
      setAdd([]);
      setRemove([]);
      queryClient.invalidateQueries({ queryKey: ['admin', 'projects'] });
    },
  });

  const members = plan.data?.members ?? [];
  const memberIds = new Set(members.map((m) => m.vas_device_id).filter((v): v is string => !!v));
  const active = project.state === 'active';
  const stray = (plan.data?.cameras ?? []).filter(
    (c) => c.vas_enabled_now && !memberIds.has(c.vas_device_id) && !add.includes(c.vas_device_id)
  );

  const inProject = (id: string) =>
    (memberIds.has(id) && !remove.includes(id)) || add.includes(id);
  const toggle = (id: string) => {
    if (memberIds.has(id)) {
      setRemove((r) => (r.includes(id) ? r.filter((x) => x !== id) : [...r, id].sort()));
    } else {
      setAdd((a) => (a.includes(id) ? a.filter((x) => x !== id) : [...a, id].sort()));
    }
  };
  const startEditing = (preAdd: string[] = []) => {
    setAdd(preAdd);
    setRemove([]);
    apply.reset();
    setEditing(true);
  };
  const changes = add.length + remove.length;

  return (
    <section className="admin-card project-cameras">
      <div className="project-cameras__header">
        <h2 className="start-project__section-title">Cameras in this project</h2>
        {!editing && (
          <button
            type="button"
            className="admin-button admin-button--secondary"
            onClick={() => startEditing()}
            disabled={!active || busy}
            title={
              !active
                ? 'Resume the project to change its cameras'
                : busy
                  ? 'Another project action is running'
                  : undefined
            }
          >
            Change cameras…
          </button>
        )}
      </div>

      {plan.isError && !plan.data && (
        <p className="admin-login__error" role="alert">
          {plan.error instanceof AdminApiError ? plan.error.message : 'Could not load the cameras'}
        </p>
      )}

      {!editing && (
        <>
          {members.length === 0 ? (
            <p className="admin-muted">
              {plan.isPending ? 'Loading…' : `${project.name} has no cameras yet.`}
            </p>
          ) : (
            <ul className="project-cameras__members">
              {members.map((m) => (
                <li key={m.device_id}>
                  <strong>{m.name}</strong>{' '}
                  <span className="admin-muted">
                    since {formatDateTime(m.joined_at)}
                    {m.inferred && ' (inferred)'}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {!active && (
            <p className="admin-muted">
              {project.name} is {project.state}: cameras can be changed only while it is active.
            </p>
          )}
          {active && stray.length > 0 && (
            <div className="project-cameras__stray" role="note">
              <span>
                Enabled in VAS but not in this project:{' '}
                <strong>{stray.map((c) => c.name).join(', ')}</strong>.
              </span>
              <button
                type="button"
                className="admin-button admin-button--secondary"
                onClick={() => startEditing(stray.filter((c) => c.device_id).map((c) => c.vas_device_id))}
                disabled={busy}
              >
                Add to project…
              </button>
            </div>
          )}
        </>
      )}

      {editing && plan.data && (
        <div className="lifecycle__preflight">
          <h3>Change cameras: what will change</h3>
          <ul className="lifecycle__effects">
            {plan.data.effects.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
          <div className="lifecycle__table-wrap">
            <table className="lifecycle__table">
              <thead>
                <tr>
                  <th scope="col">In project</th>
                  <th scope="col">Camera</th>
                  <th scope="col">In VAS now</th>
                  <th scope="col">Inference intent</th>
                  <th scope="col">What will happen</th>
                </tr>
              </thead>
              <tbody>
                {plan.data.cameras.map((c) => {
                  const changing = add.includes(c.vas_device_id) || remove.includes(c.vas_device_id);
                  return (
                    <tr key={c.vas_device_id} className={changing ? 'lifecycle__row--change' : ''}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`${c.name} in project`}
                          checked={inProject(c.vas_device_id)}
                          onChange={() => toggle(c.vas_device_id)}
                          disabled={!c.device_id || apply.isPending}
                        />
                      </td>
                      <td>
                        {c.name}
                        {!c.device_id && <span className="admin-muted"> (not synced to Ruth yet)</span>}
                      </td>
                      <td>{c.vas_enabled_now ? 'Enabled' : 'Disabled'}</td>
                      <td>
                        {c.intent ? `${c.intent} (${c.intent_models} model${c.intent_models === 1 ? '' : 's'})` : '—'}
                      </td>
                      <td>
                        <ul className="lifecycle__actions">
                          {c.actions.map((a) => (
                            <li key={a}>{a}</li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {changes > 0 && !plan.data.allowed && plan.data.blocked_reason && (
            <p className="admin-login__error" role="alert">{plan.data.blocked_reason}</p>
          )}
          {apply.isError && (
            <p className="admin-login__error" role="alert">
              {apply.error instanceof AdminApiError ? apply.error.message : 'The change did not start'}
            </p>
          )}
          {busy && <p className="admin-muted">Another project action is running (above).</p>}
          <div className="lifecycle__buttons">
            <button
              type="button"
              className="admin-button"
              onClick={() => apply.mutate()}
              disabled={changes === 0 || !plan.data.allowed || busy || apply.isPending}
            >
              {apply.isPending
                ? 'Queueing…'
                : changes === 0
                  ? 'Tick or untick cameras'
                  : `Confirm: ${[
                      add.length ? `add ${add.length}` : '',
                      remove.length ? `remove ${remove.length}` : '',
                    ]
                      .filter(Boolean)
                      .join(', ')}`}
            </button>
            <button
              type="button"
              className="admin-button admin-button--secondary"
              onClick={() => setEditing(false)}
              disabled={apply.isPending}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
