import { useMemo, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useOutletContext } from 'react-router-dom';
import {
  AdminApiError,
  fetchProjectPreflight,
  listProjects,
  startNewProject,
  type ProjectPreflight,
  type ProjectSummary,
  type StartProjectResult,
} from '../admin/adminApi';
import { useAdminSession } from '../admin/useAdminSession';
import { formatDateTime } from '../admin/format';
import { InlineAdminSignIn } from './InlineAdminSignIn';
import type { SettingsOutletContext } from './SettingsLayout';
import '../admin/AdminPages.css';
import './SettingsProjectTab.css';

/**
 * Settings -> Project. Path: /settings/project.
 *
 * Was the standalone /admin/projects page behind a route guard. It now
 * lives in Settings, which is reachable signed out, so the whole tab is
 * gated inline: there is no open endpoint for "what project is running",
 * so with no token there is genuinely nothing to show but the prompt.
 *
 * The screen's job is to make an irreversible-looking action legible before
 * it is taken, and reassuring after:
 *
 * - every number shown comes from the server's own preflight, so the counts
 *   the operator confirms are the counts that were measured;
 * - the word "archived" appears wherever a count does, because the thing
 *   operators fear here is that they are about to delete 117k records;
 * - the submit button stays disabled until the retyped name matches exactly;
 * - live inference blocks submission until the operator explicitly ticks
 *   "stop all inference", which re-runs preflight so the consequence of
 *   ticking it is visible before submitting.
 */

const TABLE_LABELS: Record<string, string> = {
  violations: 'Violations',
  events: 'Detection events',
  evidence: 'Evidence links',
  stream_sessions: 'Stream sessions',
  bookmark_analyses: 'Bookmark analyses',
};

function Counts({ counts, total }: { counts: Record<string, number>; total: number }) {
  return (
    <table className="admin-table start-project__counts">
      <thead>
        <tr>
          <th scope="col">Will be archived</th>
          <th scope="col" className="start-project__num">
            Rows
          </th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(counts).map(([table, count]) => (
          <tr key={table}>
            <td>{TABLE_LABELS[table] ?? table}</td>
            <td className="start-project__num">{count.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <th scope="row">Total</th>
          <td className="start-project__num">{total.toLocaleString()}</td>
        </tr>
      </tfoot>
    </table>
  );
}

function Blockers({
  preflight,
  stopInference,
}: {
  preflight: ProjectPreflight;
  stopInference: boolean;
}) {
  if (preflight.can_proceed) return null;

  return (
    <div className="start-project__blockers" role="alert">
      {preflight.blockers.includes('backup_unavailable') && (
        <p>
          <strong>No backup possible.</strong> The server cannot write a{' '}
          <code>pg_dump</code> to <code className="admin-mono">{preflight.backup_dir}</code>.
          This action will not run without one. Ask ops to create that
          directory (and install <code>pg_dump</code>) before continuing.
        </p>
      )}
      {preflight.blockers.includes('inference_active') && !stopInference && (
        <div>
          <p>
            <strong>
              Inference is live on {preflight.live_cameras.length}{' '}
              {preflight.live_cameras.length === 1 ? 'camera' : 'cameras'}.
            </strong>{' '}
            Archiving while detection is running would race the writer.
          </p>
          <ul className="start-project__cameras">
            {preflight.live_cameras.map((camera) => (
              <li key={camera.session_id}>
                {camera.camera_name} <span className="admin-muted">({camera.state})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {preflight.blockers.includes('too_much_data') && (
        <p>
          <strong>Unusually large archive</strong> ({preflight.total_rows.toLocaleString()}{' '}
          rows). Ask ops to run this from the CLI, where it can be supervised.
        </p>
      )}
    </div>
  );
}

function Result({ result }: { result: StartProjectResult }) {
  const total = Object.values(result.archived_counts).reduce((a, b) => a + b, 0);
  return (
    <section className="admin-card start-project__result" role="status">
      <h2 className="start-project__result-title">
        {result.new_project.name} is now the active project
      </h2>
      <p>
        {total.toLocaleString()} rows were moved to the archive from{' '}
        <strong>{result.archived_project?.name ?? 'the previous project'}</strong>.{' '}
        <strong>Nothing was deleted.</strong> No snapshot, clip or recording on
        disk was moved or removed.
      </p>
      <dl className="start-project__facts">
        <dt>Archive batch</dt>
        <dd className="admin-mono">{result.archive_batch_id ?? '—'}</dd>
        <dt>Backup</dt>
        <dd className="admin-mono">{result.backup_path ?? 'not taken'}</dd>
        {result.stopped_cameras.length > 0 && (
          <>
            <dt>Inference stopped on</dt>
            <dd>{result.stopped_cameras.join(', ')}</dd>
          </>
        )}
        <dt>VAS media paths captured</dt>
        <dd>
          {result.vas_paths_resolved.toLocaleString()} resolved,{' '}
          {result.vas_paths_missing.toLocaleString()} already removed by VAS
          retention
        </dd>
      </dl>
      <p className="admin-muted">
        Dashboards now read zero. Restoring an archived project is an ops
        action — <code>scripts/start_new_project.py --restore</code>.
      </p>
    </section>
  );
}

function ProjectRow({ project }: { project: ProjectSummary }) {
  const archived = project.archived_counts
    ? Object.values(project.archived_counts).reduce((a, b) => a + b, 0)
    : null;
  return (
    <tr>
      <td>
        {project.name}
        {project.state === 'active' && (
          <span className="admin-badge start-project__active-badge">Active</span>
        )}
      </td>
      <td>{formatDateTime(project.started_at)}</td>
      <td>{project.ended_at ? formatDateTime(project.ended_at) : '—'}</td>
      <td>{project.started_by}</td>
      <td className="start-project__num">
        {archived === null ? '—' : archived.toLocaleString()}
      </td>
    </tr>
  );
}

export function SettingsProjectTab() {
  const { sessionExpired } = useOutletContext<SettingsOutletContext>();
  const { isSignedIn } = useAdminSession();

  // Every endpoint this tab needs is admin-only, so signed out there is
  // nothing to render read-only. Returning early also means the preflight
  // poll below never starts without a token.
  if (!isSignedIn) {
    return (
      <div className="start-project__gated">
        <section className="admin-card start-project__explainer">
          <h2 className="start-project__section-title">Project lifecycle</h2>
          <p>
            Starting a new project archives this site's violations, events,
            evidence links, stream sessions and bookmark analyses, then
            begins a new project at zero. Nothing is deleted and no file on
            disk is moved.
          </p>
        </section>
        <InlineAdminSignIn
          capability="view and manage projects"
          expired={sessionExpired}
        />
      </div>
    );
  }

  return <ProjectTabContent />;
}

function ProjectTabContent() {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [confirmName, setConfirmName] = useState('');
  const [stopInference, setStopInference] = useState(false);
  const [result, setResult] = useState<StartProjectResult | null>(null);

  // Re-measured whenever the stop-inference choice changes, so the preflight
  // shown always describes the action that would actually be submitted.
  const preflight = useQuery({
    queryKey: ['admin', 'projects', 'preflight', stopInference],
    queryFn: () => fetchProjectPreflight(stopInference),
    retry: false,
    // Live inference and row counts both move; don't show a stale picture of
    // a decision this consequential.
    refetchInterval: 15_000,
  });

  const projects = useQuery({
    queryKey: ['admin', 'projects', 'list'],
    queryFn: listProjects,
    retry: false,
  });

  const start = useMutation({
    mutationFn: () =>
      startNewProject({
        name: name.trim(),
        confirm_name: confirmName.trim(),
        stop_inference: stopInference,
      }),
    onSuccess: (data) => {
      setResult(data);
      setName('');
      setConfirmName('');
      setStopInference(false);
      queryClient.invalidateQueries({ queryKey: ['admin', 'projects'] });
    },
  });

  const trimmed = name.trim();
  const namesMatch = trimmed.length >= 3 && trimmed === confirmName.trim();
  const canSubmit =
    namesMatch && preflight.data?.can_proceed === true && !start.isPending;

  const liveCount = preflight.data?.live_cameras.length ?? 0;

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (canSubmit) start.mutate();
  };

  const confirmHint = useMemo(() => {
    if (!confirmName) return null;
    if (namesMatch) return <span className="start-project__match">Matches</span>;
    return <span className="start-project__mismatch">Does not match yet</span>;
  }, [confirmName, namesMatch]);

  return (
    <div className="start-project">
      <section className="admin-card start-project__explainer">
        <h2 className="start-project__section-title">What this does</h2>
        <ul>
          <li>
            Moves the current project's rows into archive tables.{' '}
            <strong>Nothing is deleted.</strong>
          </li>
          <li>
            Leaves every file on disk exactly where it is — snapshots, clips
            and recordings are untouched.
          </li>
          <li>
            Takes a verified <code>pg_dump</code> first, and refuses to run if
            it cannot.
          </li>
          <li>
            Keeps your cameras, shift schedule and uploaded models. Only
            detection data is archived.
          </li>
          <li>
            Every dashboard counter is computed live, so they all read zero
            afterwards with nothing left to reset.
          </li>
        </ul>
      </section>

      {result && <Result result={result} />}

      <section className="admin-card">
        <h2 className="start-project__section-title">Current data</h2>
        {preflight.isPending && <p className="admin-muted">Measuring…</p>}
        {preflight.isError && (
          <p className="admin-login__error" role="alert">
            {preflight.error instanceof AdminApiError
              ? preflight.error.message
              : 'Could not run preflight'}
          </p>
        )}
        {preflight.isSuccess && (
          <>
            <p>
              Active project:{' '}
              <strong>
                {preflight.data.current_project?.name ?? 'none yet — the data below predates projects'}
              </strong>
            </p>
            <Counts
              counts={preflight.data.row_counts}
              total={preflight.data.total_rows}
            />
            <p className="admin-muted">
              {preflight.data.evidence_with_vas_media.toLocaleString()} evidence
              rows reference VAS media. Their file paths are captured into the
              archive; any VAS has already removed under its retention policy
              are recorded as unavailable.
            </p>
            <Blockers preflight={preflight.data} stopInference={stopInference} />
          </>
        )}
      </section>

      <form className="admin-card start-project__form" onSubmit={onSubmit}>
        <h2 className="start-project__section-title">Start a new project</h2>

        <label className="admin-field">
          <span className="admin-field__label">New project name</span>
          <input
            className="admin-field__input"
            type="text"
            value={name}
            maxLength={200}
            placeholder="e.g. Coke Drum Campaign 2026-Q4"
            onChange={(e) => setName(e.target.value)}
            autoComplete="off"
          />
        </label>

        <label className="admin-field">
          <span className="admin-field__label">
            Retype the name to confirm {confirmHint}
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

        {liveCount > 0 && (
          <label className="start-project__stop">
            <input
              type="checkbox"
              checked={stopInference}
              onChange={(e) => setStopInference(e.target.checked)}
            />
            <span>
              <strong>Stop all inference and proceed.</strong> Detection will
              be stopped on {liveCount} {liveCount === 1 ? 'camera' : 'cameras'}
              , and the archive waits for each to wind down before it starts.
              Video streams keep running; restart detection yourself
              afterwards.
            </span>
          </label>
        )}

        {start.isError && (
          <p className="admin-login__error" role="alert">
            {start.error instanceof AdminApiError
              ? start.error.message
              : 'Could not start the project'}
          </p>
        )}

        <button className="admin-button admin-button--danger" type="submit" disabled={!canSubmit}>
          {start.isPending
            ? 'Backing up and archiving…'
            : `Archive and start${trimmed ? ` “${trimmed}”` : ''}`}
        </button>
        {start.isPending && (
          <p className="admin-muted">
            Taking the backup, then archiving in one transaction. This can take
            a few minutes; do not reload.
          </p>
        )}
      </form>

      <section className="admin-card">
        <h2 className="start-project__section-title">Project history</h2>
        {projects.isPending && <p className="admin-muted">Loading…</p>}
        {projects.isSuccess && projects.data.items.length === 0 && (
          <p className="admin-muted">No projects yet.</p>
        )}
        {projects.isSuccess && projects.data.items.length > 0 && (
          <table className="admin-table">
            <thead>
              <tr>
                <th scope="col">Project</th>
                <th scope="col">Started</th>
                <th scope="col">Ended</th>
                <th scope="col">By</th>
                <th scope="col" className="start-project__num">
                  Rows archived
                </th>
              </tr>
            </thead>
            <tbody>
              {projects.data.items.map((project) => (
                <ProjectRow key={project.id} project={project} />
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
