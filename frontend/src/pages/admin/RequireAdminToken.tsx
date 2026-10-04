import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { adminLoginUrl, getAdminToken } from './adminApi';

/**
 * Route guard for admin pages: no admin token -> admin login.
 *
 * Presence check only. Whether the token is still valid is decided by the
 * server; adminFetch handles the 401 by clearing it and redirecting here.
 */
export function RequireAdminToken({ children }: { children: ReactNode }) {
  const location = useLocation();
  if (!getAdminToken()) {
    return <Navigate to={adminLoginUrl(location.pathname + location.search)} replace />;
  }
  return <>{children}</>;
}
