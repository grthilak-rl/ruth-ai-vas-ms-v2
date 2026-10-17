import { Navigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useHasRole, type UserRole } from '../../state';

interface RequireRoleProps {
  /** Minimum required role to access this route */
  requiredRole: UserRole;
  /** Child component to render if authorized */
  children: ReactNode;
  /** Route to redirect to if unauthorized (default: /forbidden) */
  redirectTo?: string;
}

/**
 * Route Guard Component (E11)
 *
 * Wraps route elements to enforce role-based access.
 *
 * Per F2 §Permission Enforcement:
 * - Unauthorized access to role-gated routes → 403 page
 * - Deep links to forbidden screens → 403 with "Contact Admin" message
 *
 * Per F6: Role gates UI only. Backend enforces actual permissions.
 *
 * Usage:
 * ```tsx
 * <Route
 *   path="/analytics"
 *   element={
 *     <RequireRole requiredRole="supervisor">
 *       <AnalyticsPage />
 *     </RequireRole>
 *   }
 * />
 * ```
 *
 * There is no RequireAdmin wrapper. Settings was its only consumer and now
 * gates on the admin token instead (useAdminSession), because the role
 * these guards read is hardcoded to 'admin' in AuthContext with a TODO and
 * nothing ever calls login() — so an admin role gate protects nothing today
 * and would hide the page outright the day real auth lands. Use
 * `RequireRole requiredRole="admin"` directly if a genuinely role-gated
 * admin route ever appears.
 */
export function RequireRole({
  requiredRole,
  children,
  redirectTo = '/forbidden',
}: RequireRoleProps) {
  const hasAccess = useHasRole(requiredRole);

  if (!hasAccess) {
    // Navigate to 403 page, preserving the attempted URL in state
    // for potential "Go back" functionality
    return <Navigate to={redirectTo} replace />;
  }

  return <>{children}</>;
}

/**
 * Convenience wrapper for Supervisor+ routes
 */
export function RequireSupervisor({ children }: { children: ReactNode }) {
  return <RequireRole requiredRole="supervisor">{children}</RequireRole>;
}

