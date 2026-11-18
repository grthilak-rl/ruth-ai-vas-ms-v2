/**
 * Auth context object, types and hooks. Kept apart from the provider
 * component (AuthContext.tsx) so React fast refresh works on both.
 */

import { createContext, useContext } from 'react';

/**
 * User Role
 *
 * Per F6: Role gates UI only. Backend enforces actual permissions.
 * Frontend handles 403 gracefully, does not infer permissions from role.
 */
export type UserRole = 'operator' | 'supervisor' | 'admin';

export interface User {
  id: string;
  email: string;
  name: string;
  role: UserRole;
}

export interface AuthContextValue {
  /** Whether user is authenticated (token exists and is valid) */
  isAuthenticated: boolean;

  /** Current user info (null if not authenticated) */
  user: User | null;

  /** Current user role (defaults to 'operator' if unknown) */
  role: UserRole;

  /** Whether auth state is still loading */
  isLoading: boolean;

  /** Login function */
  login: (token: string, user: User) => void;

  /** Logout function */
  logout: () => void;

  /** Get current auth token */
  getToken: () => string | null;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export const TOKEN_KEY = 'auth_token';
export const USER_KEY = 'auth_user';

/**
 * Hook to access auth context
 */
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

/**
 * Hook to check if user has specific role
 *
 * Note: This gates UI visibility only. Backend enforces actual permissions.
 */
export function useHasRole(requiredRole: UserRole): boolean {
  const { role } = useAuth();

  const roleHierarchy: Record<UserRole, number> = {
    operator: 0,
    supervisor: 1,
    admin: 2,
  };

  return roleHierarchy[role] >= roleHierarchy[requiredRole];
}

/**
 * Hook to check if user is admin
 */
export function useIsAdmin(): boolean {
  return useHasRole('admin');
}

/**
 * Hook to check if user is at least supervisor
 */
export function useIsSupervisor(): boolean {
  return useHasRole('supervisor');
}
