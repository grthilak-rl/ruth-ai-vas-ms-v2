import { useMemo, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useOutletContext } from 'react-router-dom';
import { useModelsStatusQuery } from '../../state';
import { AdminApiError, createStoreModel, listStoreModels } from '../admin/adminApi';
import { useAdminSession } from '../admin/useAdminSession';
import { formatBytes, formatDateTime } from '../admin/format';
import { InlineAdminSignIn } from './InlineAdminSignIn';
import type { SettingsOutletContext } from './SettingsLayout';
import {
  mergeModels,
  UPLOADED_STATE_HINT,
  UPLOADED_STATE_LABEL,
  type MergedModel,
} from './mergeModels';
import './SettingsModelsTab.css';

/**
 * Settings -> AI Models.
 *
 * One list of every model in the deployment, built-in and uploaded,
 * replacing both the old Settings "AI Models" page (which showed uploaded
 * models as raw slugs with no indication they were uploaded) and the Model
 * Management page (which knew about files and runtime but nothing about
 * health or camera usage).
 *
 * Two sources, merged as a union — see mergeModels.ts for why each of the
 * four uploaded states exists and why an inner join would be wrong.
 *
 * Signed out the list still renders from the open /models/status endpoint;
 * only the manage affordances are gated.
 */

/** Where an operator finds the install procedure. */
const RUNBOOK_HREF =
  'https://github.com/visics/ruth-ai-vas-ms-v2/blob/main/docs/model-store/README.md';

function HealthDot({ health }: { health: string }) {
  return (
    <span
      className={`models-tab__dot models-tab__dot--${health}`}
      aria-hidden="true"
    />
  );
}

function BuiltInRow({ model }: { model: MergedModel }) {
  const status = model.status!;
  return (
    <tr>
      <td className="models-tab__name">{model.displayName}</td>
      <td className="models-tab__mono">{status.version}</td>
      <td>
        <HealthDot health={status.health} />
        {status.health}
      </td>
      <td>{status.status}</td>
      <td className="models-tab__num">{status.cameras_active}</td>
      <td className="models-tab__muted">
        {status.last_inference_at ? formatDateTime(status.last_inference_at) : '—'}
      </td>
    </tr>
  );
}

function UploadedRow({ model }: { model: MergedModel }) {
  const state = model.uploadedState!;
  const hint = UPLOADED_STATE_HINT[state];
  const status = model.status;
  const store = model.store;

  return (
    <>
      <tr>
        <td className="models-tab__name">
          {store ? (
            <Link to={`/settings/models/${store.id}`}>{model.displayName}</Link>
          ) : (
            model.displayName
          )}
          <div className="models-tab__model-id">{model.model_id}</div>
        </td>
        <td className="models-tab__mono">{status?.version ?? '—'}</td>
        <td>
          {status ? (
            <>
              <HealthDot health={status.health} />
              {status.health}
            </>
          ) : (
            <span className="models-tab__muted">—</span>
          )}
        </td>
        <td>
          <span className={`models-tab__state models-tab__state--${state}`}>
            {UPLOADED_STATE_LABEL[state]}
          </span>
        </td>
        <td className="models-tab__num">{status?.cameras_active ?? '—'}</td>
        <td className="models-tab__muted">
          {store ? `${store.file_count} files · ${formatBytes(store.total_bytes)}` : '—'}
        </td>
      </tr>
      {hint && (
        <tr className="models-tab__hint-row">
          <td colSpan={6}>
            <span className="models-tab__hint">
              {hint}
              {state === 'not_installed' && (
                <>
                  {' '}
                  <a href={RUNBOOK_HREF} target="_blank" rel="noreferrer">
                    Installation runbook
                  </a>
                  .
                </>
              )}
            </span>
            {/*
              Enable / Apply lands here. It is the next workstream (Store
              Step 5 piece 3 + Steps 3-4): installing into enabled/ is
              currently install_enabled.py plus a runtime restart, with no
              API behind it. The row is shaped so the action slots into
              this cell without moving anything above it.
            */}
          </td>
        </tr>
      )}
    </>
  );
}

export function SettingsModelsTab() {
  const { sessionExpired } = useOutletContext<SettingsOutletContext>();
  const { isSignedIn } = useAdminSession();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState('');

  // Open endpoint: always queried, signed in or not.
  const status = useModelsStatusQuery();

  // Admin endpoint: only when a token exists. `enabled` means this query
  // stops and restarts cleanly as the session comes and goes, instead of
  // firing a doomed request and relying on the 401 path.
  const storeModels = useQuery({
    queryKey: ['admin', 'model-store', 'models'],
    queryFn: listStoreModels,
    enabled: isSignedIn,
    retry: false,
  });

  const create = useMutation({
    mutationFn: (name: string) => createStoreModel(name),
    onSuccess: (model) => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'model-store'] });
      navigate(`/settings/models/${model.id}`);
    },
  });

  const merged = useMemo(
    () =>
      mergeModels({
        statusModels: status.data?.models ?? [],
        storeRuntime: status.data?.store_runtime,
        // Undefined (not []) while signed out or still loading, so the
        // merge can tell "no upload records" from "cannot see them".
        storeModels: isSignedIn && storeModels.isSuccess ? storeModels.data : undefined,
      }),
    [status.data, storeModels.isSuccess, storeModels.data, isSignedIn]
  );

  const onCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (displayName.trim()) create.mutate(displayName.trim());
  };

  const healthy = merged.builtIn.filter((m) => m.status?.health === 'healthy').length;
  const totalWithStatus = merged.builtIn.length + merged.uploaded.filter((m) => m.status).length;
  const healthyTotal =
    healthy + merged.uploaded.filter((m) => m.status?.health === 'healthy').length;

  return (
    <div className="models-tab">
      <div className="models-tab__summary">
        {status.isSuccess && (
          <span>
            {healthyTotal}/{totalWithStatus} models healthy
          </span>
        )}
        {merged.storeRuntimeConfigured && (
          <span
            className={`models-tab__runtime models-tab__runtime--${
              merged.runtimeUnreachable ? 'down' : 'up'
            }`}
          >
            Store runtime: {merged.runtimeUnreachable ? 'unreachable' : 'running'}
          </span>
        )}
      </div>

      {status.isError && (
        <p className="models-tab__error" role="alert">
          Unable to load model status. The AI Runtime may be unreachable.{' '}
          <button type="button" onClick={() => status.refetch()}>
            Retry
          </button>
        </p>
      )}

      {merged.runtimeUnreachable && (
        <p className="models-tab__warning" role="status">
          The store runtime did not respond, so uploaded models cannot be
          confirmed as running. Built-in models are unaffected.
        </p>
      )}

      {/* ---------------- Built-in ---------------- */}
      <section className="models-tab__section">
        <h2 className="models-tab__section-title">Built-in models</h2>
        {status.isPending && <p className="models-tab__muted">Loading…</p>}
        {status.isSuccess && merged.builtIn.length === 0 && (
          <p className="models-tab__muted">
            No built-in models reported by the AI Runtime.
          </p>
        )}
        {merged.builtIn.length > 0 && (
          <table className="models-tab__table">
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Version</th>
                <th scope="col">Health</th>
                <th scope="col">Status</th>
                <th scope="col" className="models-tab__num">Cameras</th>
                <th scope="col">Last inference</th>
              </tr>
            </thead>
            <tbody>
              {merged.builtIn.map((model) => (
                <BuiltInRow key={model.key} model={model} />
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* ---------------- Uploaded ---------------- */}
      <section className="models-tab__section">
        <div className="models-tab__section-header">
          <h2 className="models-tab__section-title">Uploaded models</h2>
        </div>

        {merged.uploaded.length > 0 && (
          <table className="models-tab__table">
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Version</th>
                <th scope="col">Health</th>
                <th scope="col">State</th>
                <th scope="col" className="models-tab__num">Cameras</th>
                <th scope="col">Files</th>
              </tr>
            </thead>
            <tbody>
              {merged.uploaded.map((model) => (
                <UploadedRow key={model.key} model={model} />
              ))}
            </tbody>
          </table>
        )}

        {merged.uploaded.length === 0 && (
          <p className="models-tab__muted">
            {isSignedIn
              ? 'No uploaded models yet.'
              : 'No uploaded models are currently running.'}
          </p>
        )}

        {isSignedIn ? (
          <form className="models-tab__create" onSubmit={onCreate}>
            <label className="models-tab__create-field">
              <span className="models-tab__create-label">Add a model</span>
              <input
                className="models-tab__create-input"
                type="text"
                placeholder="Display name, e.g. PPE six items"
                maxLength={128}
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
              />
            </label>
            <button
              className="models-tab__create-submit"
              type="submit"
              disabled={!displayName.trim() || create.isPending}
            >
              {create.isPending ? 'Creating…' : 'Create and upload files'}
            </button>
            {create.isError && (
              <p className="models-tab__error" role="alert">
                {create.error instanceof AdminApiError
                  ? create.error.message
                  : 'Could not create the model'}
              </p>
            )}
          </form>
        ) : (
          <InlineAdminSignIn
            capability="upload or manage models"
            expired={sessionExpired}
          />
        )}

        {isSignedIn && storeModels.isError && (
          <p className="models-tab__error" role="alert">
            {storeModels.error instanceof AdminApiError
              ? storeModels.error.message
              : 'Could not load uploaded models.'}
          </p>
        )}
      </section>
    </div>
  );
}
