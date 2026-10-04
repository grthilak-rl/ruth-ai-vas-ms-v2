import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { ADMIN_LOGIN_PATH, clearAdminToken, fetchAdminMe } from './adminApi';
import './AdminPages.css';

/**
 * Model Management (placeholder)
 * Path: /admin/models — behind RequireAdminToken.
 *
 * Loads /api/v1/admin/me to prove the admin session end to end. Upload, list
 * and status arrive in the next step.
 */
export function ModelManagementPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ['admin', 'me'],
    queryFn: fetchAdminMe,
    retry: false,
    staleTime: 60_000,
  });

  const signOut = () => {
    clearAdminToken();
    queryClient.removeQueries({ queryKey: ['admin'] });
    navigate(ADMIN_LOGIN_PATH, { replace: true });
  };

  return (
    <div className="admin-page">
      <header className="admin-page__header">
        <div>
          <h1 className="admin-page__title">Model Management</h1>
          <p className="admin-page__subtitle">
            {me.isPending && 'Checking admin session…'}
            {me.isSuccess && (
              <>
                Signed in as <strong>{me.data.username}</strong>
              </>
            )}
            {me.isError && 'Could not load the admin session.'}
          </p>
        </div>
        <button className="admin-button admin-button--secondary" type="button" onClick={signOut}>
          Sign out
        </button>
      </header>

      <div className="admin-card admin-placeholder">
        <p className="admin-placeholder__text">Model Management — coming soon</p>
      </div>
    </div>
  );
}
