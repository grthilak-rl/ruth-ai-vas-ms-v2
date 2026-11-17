import { useMemo, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useOutletContext } from 'react-router-dom';
import {
  AdminApiError,
  fetchStartPreflight,
  listProjects,
  startNextProject,
  type ProjectJob,
  type ProjectSummary,
} from '../admin/adminApi';
import { useAdminSession } from '../admin/useAdminSession';
import { formatDateTime } from '../admin/format';
import { useProjectView } from '../../state/project/projectView';
import { projectQueryKeys, type ProjectBrief } from '../../state/project/projectsApi';
import { formatDay } from '../../components/project/projectPages';
import { InlineAdminSignIn } from './InlineAdminSignIn';
import { ProjectCamerasCard } from './ProjectCamerasCard';
import { ProjectJobProgress } from './ProjectJobProgress';
import { ProjectLifecyclePanel } from './ProjectLifecyclePanel';
import { useProjectJobs } from './useProjectJobs';
import type { SettingsOutletContext } from './SettingsLayout';
import '../admin/AdminPages.css';
import './ProjectLifecyclePanel.css';
import './SettingsProjectTab.css';

/**
 * Settings -> Project. Path: /settings/project.
 *
 * Projects are tags: every violation, report and export says which project
 * it belongs to, and nothing is archived or deleted when a project ends.
 *
 * - Every project is listed with "Open", which puts the whole portal into
 *   that project's context (banner + ?project= in the URL). Viewing is open
 *   to every portal user, like the Violations page.
 * - Signed in as admin: Stop / Resume / End the current project, and once it
 *   is ended, start the next one with the cameras it should run. Footage
 *   deletion is never un-paused here (Settings -> System does that).
 */

const TABLE_LABELS: Record<string, string> = {
  violations: 'violations',
  evidence: 'evidence',
  events: 'events',
  stream_sessions: 'sessions',
  customer_reports: 'reports',
  violation_exports: 'exports',
};

const STATE_LABELS: Record<string, string> = {
  active: 'Active',
  stopping: 'Stopping',
  stopped: 'Stopped',
  resuming: 'Resuming',
  ended: 'Ended',
  archived: 'Ended',
};

function countsText(counts: Record<string, number> | null | undefined): string {
  if (!counts) return '—';
  const parts = ['violations', 'customer_reports', 'violation_exports']
    .filter((k) => counts[k])
    .map((k) => `${counts[k].toLocaleString()} ${TABLE_LABELS[k]}`);
  return parts.length ? parts.join(' · ') : 'no data';
}

export function SettingsProjectTab() {
  const { sessionExpired } = useOutletContext<SettingsOutletContext>();
  const { isSignedIn } = useAdminSession();
  const adminList = useQuery({
    queryKey: ['admin', 'projects', 'list'],
    queryFn: listProjects,
    retry: false,
    enabled: isSignedIn,
  });

  return (
    <div className="start-project">
      {isSignedIn && <CurrentProjectAdmin list={adminList.data} loading={adminList.isPending} />}
      <ProjectsTable admin={isSignedIn ? adminList.data?.items : undefined} />
      {!isSignedIn && (
        <InlineAdminSignIn capability="stop, end and start projects" expired={sessionExpired} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Every project, with Open
// ---------------------------------------------------------------------------

function ProjectsTable({ admin }: { admin?: ProjectSummary[] }) {
  const { projects, viewed, current, openProject, exitProject } = useProjectView();
  const byId = useMemo(() => new Map((admin ?? []).map((p) => [p.id, p])), [admin]);

  return (
    <section className="admin-card">
      <h2 className="start-project__section-title">Projects</h2>
      {projects.length > 0 && !current && (
        <p className="project-list__no-current" role="status">
          No current project. Every project has ended; start the next one to switch cameras
          back on.
        </p>
      )}
      <p className="admin-muted">
        Open a project to see its violations, analytics, reports and exports. Nothing
        is archived or deleted when a project ends. Live pages (Cameras, live view,
        System Health) always show the current setup.
      </p>
      {projects.length === 0 ? (
        <p className="admin-muted">Loading…</p>
      ) : (
        <div className="lifecycle__table-wrap">
          <table className="admin-table project-list">
            <thead>
              <tr>
                <th scope="col">Project</th>
                <th scope="col">Started</th>
                <th scope="col">Ended</th>
                {admin && <th scope="col">Data</th>}
                <th scope="col" aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <ProjectRow
                  key={p.id}
                  project={p}
                  summary={byId.get(p.id)}
                  showCounts={!!admin}
                  isViewed={viewed?.id === p.id}
                  isCurrent={current?.id === p.id}
                  onOpen={() => openProject(p.slug)}
                  onBack={exitProject}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ProjectRow({
  project,
  summary,
  showCounts,
  isViewed,
  isCurrent,
  onOpen,
  onBack,
}: {
  project: ProjectBrief;
  summary?: ProjectSummary;
  showCounts: boolean;
  isViewed: boolean;
  isCurrent: boolean;
  onOpen: () => void;
  onBack: () => void;
}) {
  return (
    <tr className={isViewed ? 'project-list__row--viewed' : undefined}>
      <td>
        <strong>{project.name}</strong>{' '}
        <span className={`admin-badge project-list__state project-list__state--${project.state}`}>
          {STATE_LABELS[project.state] ?? project.state}
        </span>
        {isCurrent && <span className="admin-badge start-project__active-badge">Current</span>}
        {isViewed && <span className="admin-badge project-list__viewing">Viewing</span>}
      </td>
      <td>{formatDay(project.started_at)}</td>
      <td>{project.ended_at ? formatDay(project.ended_at) : '—'}</td>
      {showCounts && <td>{countsText(summary?.counts)}</td>}
      <td className="project-list__action">
        {isViewed ? (
          <button type="button" className="admin-button admin-button--secondary" onClick={onBack}>
            Back to current
          </button>
        ) : (
          <button type="button" className="admin-button admin-button--secondary" onClick={onOpen}>
            {isCurrent ? 'Open current' : 'Open'}
          </button>
        )}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Admin: the current project's lifecycle, or Start the next one
// ---------------------------------------------------------------------------

function CurrentProjectAdmin({
  list,
  loading,
}: {
  list?: { items: ProjectSummary[]; active: ProjectSummary | null };
  loading: boolean;
}) {
  const jobs = useProjectJobs();
  if (loading) return <p className="admin-muted">Loading projects…</p>;
  const active = list?.active ?? null;
  const last = list?.items[0] ?? null;
  const shown = jobs.shown;

  return (
    <>
      {shown && (
        <ProjectJobProgress
          job={shown}
          onRetry={() => jobs.retry.mutate(shown.id)}
          retrying={jobs.retry.isPending}
          retryError={jobs.retry.error}
          onDismiss={() => jobs.dismiss(shown.id)}
        />
      )}
      {active ? (
        <>
          <ProjectLifecyclePanel project={active} busy={jobs.busy} onQueued={jobs.track} />
          <ProjectCamerasCard project={active} busy={jobs.busy} onQueued={jobs.track} />
          <section className="admin-card">
            <h2 className="start-project__section-title">Start the next project</h2>
            <p className="admin-muted">
              End <strong>{active.name}</strong> first (above). Its data stays here and can
              be opened any time; then start the next project with the cameras it should run.
            </p>
          </section>
        </>
      ) : (
        <StartNextProject last={last} busy={jobs.busy} onQueued={jobs.track} />
      )}
    </>
  );
}

export function StartNextProject({
  last,
  busy,
  onQueued,
}: {
  last: ProjectSummary | null;
  busy: boolean;
  onQueued: (job: ProjectJob) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [confirmName, setConfirmName] = useState('');
  // Nothing is ticked by default. After End every camera is disabled, so
  // "the cameras enabled now" would always be none (that is how Post HPCL
  // Dev was started with no cameras on 17 Nov).
  const [chosen, setChosen] = useState<string[]>([]);
  const [noCameras, setNoCameras] = useState(false);

  const preflight = useQuery({
    queryKey: ['admin', 'projects', 'start-preflight', chosen],
    queryFn: () => fetchStartPreflight(chosen),
    retry: false,
    placeholderData: (prev) => prev,
  });

  const start = useMutation({
    mutationFn: () =>
      startNextProject({
        name: name.trim(),
        confirm_name: confirmName.trim(),
        camera_ids: chosen,
        allow_no_cameras: chosen.length === 0 && noCameras,
      }),
    onSuccess: (job) => {
      onQueued(job);
      setName('');
      setConfirmName('');
      setChosen([]);
      setNoCameras(false);
      queryClient.invalidateQueries({ queryKey: ['admin', 'projects'] });
      queryClient.invalidateQueries({ queryKey: projectQueryKeys.list });
    },
  });

  const trimmed = name.trim();
  const namesMatch = trimmed.length >= 3 && trimmed === confirmName.trim();
  const camerasOk = chosen.length > 0 || noCameras;
  const canSubmit =
    namesMatch && camerasOk && preflight.data?.can_proceed === true && !start.isPending && !busy;
  const selected = new Set(chosen);
  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChosen([...next].sort());
  };

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (canSubmit) start.mutate();
  };

  return (
    <form className="admin-card start-project__form" onSubmit={onSubmit}>
      <h2 className="start-project__section-title">Start the next project</h2>
      {last && (
        <p className="admin-muted">
          {last.name} {last.ended_at ? `ended ${formatDateTime(last.ended_at)}` : `is ${last.state}`}. Its
          data stays viewable from the list below.
        </p>
      )}

      {preflight.isError && (
        <p className="admin-login__error" role="alert">
          {preflight.error instanceof AdminApiError ? preflight.error.message : 'Could not check the cameras'}
        </p>
      )}
      {preflight.data && !preflight.data.can_proceed && (
        <p className="admin-login__error" role="alert">{preflight.data.blocked_reason}</p>
      )}

      <label className="admin-field">
        <span className="admin-field__label">New project name</span>
        <input
          className="admin-field__input"
          type="text"
          value={name}
          maxLength={200}
          placeholder="e.g. Post HPCL Dev"
          onChange={(e) => setName(e.target.value)}
          autoComplete="off"
        />
      </label>
      <label className="admin-field">
        <span className="admin-field__label">
          Retype the name to confirm{' '}
          {confirmName &&
            (namesMatch ? (
              <span className="start-project__match">Matches</span>
            ) : (
              <span className="start-project__mismatch">Does not match yet</span>
            ))}
        </span>
        <input
          className="admin-field__input"
          type="text"
          value={confirmName}
          maxLength={200}
          placeholder="Type the exact name again"
          onChange={(e) => setConfirmName(e.target.value)}
          autoComplete="off"
        />
      </label>

      <fieldset className="start-project__picker">
        <legend className="admin-field__label">
          Cameras this project runs ({selected.size} selected). Ticked cameras are
          enabled in VAS; the rest are disabled. Models per camera are kept.
        </legend>
        {preflight.isPending && <p className="admin-muted">Checking every camera…</p>}
        {preflight.data && (
          <div className="lifecycle__table-wrap">
            <table className="lifecycle__table">
              <thead>
                <tr>
                  <th scope="col">Run</th>
                  <th scope="col">Camera</th>
                  <th scope="col">In VAS now</th>
                  <th scope="col">Inference intent</th>
                  <th scope="col">What will happen</th>
                </tr>
              </thead>
              <tbody>
                {preflight.data.cameras.map((c) => (
                  <tr key={c.vas_device_id} className={c.vas_change ? 'lifecycle__row--change' : ''}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Run ${c.name}`}
                        checked={selected.has(c.vas_device_id)}
                        onChange={() => toggle(c.vas_device_id)}
                        disabled={!c.device_id}
                      />
                    </td>
                    <td>
                      {c.name}
                      {!c.device_id && <span className="admin-muted"> (not synced to Ruth yet)</span>}
                    </td>
                    <td>{c.vas_enabled_now ? 'Enabled' : 'Disabled'}</td>
                    <td>{c.intent ? `${c.intent} (${c.intent_models} model${c.intent_models === 1 ? '' : 's'})` : '—'}</td>
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
        )}
      </fieldset>

      {chosen.length === 0 && (
        <label className="start-project__no-cameras">
          <input type="checkbox" checked={noCameras} onChange={(e) => setNoCameras(e.target.checked)} />
          <span>
            Start with <strong>no cameras</strong>: every camera stays disabled until one is
            enabled on the Cameras page.
          </span>
        </label>
      )}

      {preflight.data && (
        <ul className="lifecycle__effects">
          {preflight.data.effects.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}

      {start.isError && (
        <p className="admin-login__error" role="alert">
          {start.error instanceof AdminApiError ? start.error.message : 'Could not start the project'}
        </p>
      )}
      {namesMatch && !camerasOk && (
        <p className="admin-muted" role="note">
          Tick the cameras this project runs, or confirm starting with no cameras.
        </p>
      )}
      {busy && <p className="admin-muted">Another project action is running (above).</p>}
      <button className="admin-button" type="submit" disabled={!canSubmit}>
        {start.isPending
          ? 'Queueing…'
          : `Start${trimmed ? ` “${trimmed}”` : ''}${chosen.length ? ` with ${chosen.length} camera${chosen.length === 1 ? '' : 's'}` : ''}`}
      </button>
    </form>
  );
}
