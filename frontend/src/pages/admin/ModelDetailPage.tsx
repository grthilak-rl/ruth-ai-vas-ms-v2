import { useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  AdminApiError,
  deleteStoreFile,
  deleteStoreModel,
  getStoreModel,
  type StoreFile,
} from './adminApi';
import { ModelUploader } from './ModelUploader';
import { formatBytes, formatDateTime } from './format';
import './AdminPages.css';

/**
 * Model Management — one model
 * Path: /admin/models/:modelPk — behind RequireAdminToken.
 */
export function ModelDetailPage() {
  const { modelPk = '' } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const queryKey = ['admin', 'model-store', 'model', modelPk];

  const model = useQuery({
    queryKey,
    queryFn: () => getStoreModel(modelPk),
    retry: false,
  });

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['admin', 'model-store'] });
  }, [queryClient]);

  const removeFile = useMutation({
    mutationFn: (file: StoreFile) => deleteStoreFile(modelPk, file.id),
    onSettled: refresh,
  });
  const removeModel = useMutation({
    mutationFn: () => deleteStoreModel(modelPk),
    onSuccess: () => {
      refresh();
      navigate('/admin/models', { replace: true });
    },
  });

  if (model.isPending) {
    return <div className="admin-page"><p className="admin-muted">Loading…</p></div>;
  }
  if (model.isError) {
    return (
      <div className="admin-page">
        <Link to="/admin/models" className="admin-back">← All models</Link>
        <p className="admin-login__error" role="alert">
          {model.error instanceof AdminApiError && model.error.status === 404
            ? 'This model does not exist or was deleted.'
            : 'Could not load the model.'}
        </p>
      </div>
    );
  }

  const data = model.data;
  const confirmDeleteModel = () => {
    if (
      window.confirm(
        `Delete draft "${data.display_name}"? Its files move to trash and the model ID ` +
          `"${data.model_id}" can never be used again.`
      )
    ) {
      removeModel.mutate();
    }
  };
  const confirmDeleteFile = (file: StoreFile) => {
    if (window.confirm(`Delete ${file.filename} from this draft?`)) removeFile.mutate(file);
  };

  return (
    <div className="admin-page">
      <Link to="/admin/models" className="admin-back">← All models</Link>
      <header className="admin-page__header">
        <div>
          <h1 className="admin-page__title">{data.display_name}</h1>
          <p className="admin-page__subtitle">
            Model ID <span className="admin-mono">{data.model_id}</span> · {data.state} ·{' '}
            {data.file_count} file{data.file_count === 1 ? '' : 's'}, {formatBytes(data.total_bytes)}
          </p>
        </div>
        <button
          className="admin-button admin-button--danger"
          type="button"
          onClick={confirmDeleteModel}
          disabled={removeModel.isPending}
        >
          Delete draft
        </button>
      </header>

      {(removeModel.isError || removeFile.isError) && (
        <p className="admin-login__error" role="alert">
          {(removeModel.error ?? removeFile.error) instanceof AdminApiError
            ? ((removeModel.error ?? removeFile.error) as AdminApiError).message
            : 'Delete failed'}
        </p>
      )}

      <ModelUploader modelPk={modelPk} activeUploads={data.active_uploads} onChanged={refresh} />

      <section className="admin-card">
        <h2 className="admin-card__title">Files</h2>
        {data.files.length === 0 ? (
          <p className="admin-muted">No files uploaded yet.</p>
        ) : (
          <table className="admin-table">
            <thead>
              <tr>
                <th>File</th>
                <th>Size</th>
                <th>SHA-256</th>
                <th>Uploaded</th>
                <th>By</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {data.files.map((file) => (
                <tr key={file.id}>
                  <td className="admin-mono">{file.filename}</td>
                  <td>{formatBytes(file.size_bytes)}</td>
                  <td className="admin-mono admin-sha" title={file.sha256}>
                    {file.sha256}
                  </td>
                  <td>{formatDateTime(file.uploaded_at)}</td>
                  <td>{file.uploaded_by ?? '—'}</td>
                  <td>
                    <span className="admin-badge admin-badge--uploaded">Uploaded</span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="admin-button admin-button--link"
                      onClick={() => confirmDeleteFile(file)}
                      disabled={removeFile.isPending}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
