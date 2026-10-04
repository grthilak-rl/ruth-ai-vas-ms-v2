import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import {
  ADMIN_LOGIN_PATH,
  AdminApiError,
  clearAdminToken,
  createStoreModel,
  fetchAdminMe,
  listStoreModels,
} from './adminApi';
import { formatBytes, formatDateTime } from './format';
import './AdminPages.css';

/**
 * Model Management — model list
 * Path: /admin/models — behind RequireAdminToken.
 */
export function ModelManagementPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState('');

  const me = useQuery({
    queryKey: ['admin', 'me'],
    queryFn: fetchAdminMe,
    retry: false,
    staleTime: 60_000,
  });
  const models = useQuery({
    queryKey: ['admin', 'model-store', 'models'],
    queryFn: listStoreModels,
    retry: false,
  });
  const create = useMutation({
    mutationFn: (name: string) => createStoreModel(name),
    onSuccess: (model) => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'model-store'] });
      navigate(`/admin/models/${model.id}`);
    },
  });

  const signOut = () => {
    clearAdminToken();
    queryClient.removeQueries({ queryKey: ['admin'] });
    navigate(ADMIN_LOGIN_PATH, { replace: true });
  };

  const onCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (displayName.trim()) create.mutate(displayName.trim());
  };

  return (
    <div className="admin-page">
      <header className="admin-page__header">
        <div>
          <h1 className="admin-page__title">Model Management</h1>
          <p className="admin-page__subtitle">
            {me.isSuccess ? (
              <>
                Signed in as <strong>{me.data.username}</strong>
              </>
            ) : (
              'Upload trained models for integration'
            )}
          </p>
        </div>
        <button className="admin-button admin-button--secondary" type="button" onClick={signOut}>
          Sign out
        </button>
      </header>

      <form className="admin-card admin-new-model" onSubmit={onCreate}>
        <label className="admin-field admin-new-model__field">
          <span className="admin-field__label">New model</span>
          <input
            className="admin-field__input"
            type="text"
            placeholder="Display name, e.g. PPE six items"
            maxLength={128}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </label>
        <button className="admin-button" type="submit" disabled={!displayName.trim() || create.isPending}>
          {create.isPending ? 'Creating…' : 'Create'}
        </button>
        {create.isError && (
          <p className="admin-login__error admin-new-model__error" role="alert">
            {create.error instanceof AdminApiError ? create.error.message : 'Could not create the model'}
          </p>
        )}
      </form>

      <section className="admin-card">
        {models.isPending && <p className="admin-muted">Loading models…</p>}
        {models.isError && (
          <p className="admin-login__error" role="alert">
            {models.error instanceof AdminApiError ? models.error.message : 'Could not load models'}
          </p>
        )}
        {models.isSuccess && models.data.length === 0 && (
          <p className="admin-muted">No models yet. Create one above, then upload its weight files.</p>
        )}
        {models.isSuccess && models.data.length > 0 && (
          <table className="admin-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Model ID</th>
                <th>Files</th>
                <th>Size</th>
                <th>Status</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {models.data.map((model) => (
                <tr key={model.id}>
                  <td>
                    <Link to={`/admin/models/${model.id}`}>{model.display_name}</Link>
                  </td>
                  <td className="admin-mono">{model.model_id}</td>
                  <td>{model.file_count}</td>
                  <td>{formatBytes(model.total_bytes)}</td>
                  <td>
                    <span className={`admin-badge admin-badge--${model.status}`}>
                      {model.status === 'uploaded' ? 'Uploaded' : 'No files'}
                    </span>
                  </td>
                  <td>{formatDateTime(model.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
