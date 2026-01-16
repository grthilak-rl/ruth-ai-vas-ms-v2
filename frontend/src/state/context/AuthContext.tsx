import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from 'react';

/**
 * User Role
 *
 * Per F6: Role gates UI only. Backend enforces actual permissions.
 * Frontend handles 403 gracefully, does not infer permissions from role.
 */
export type UserRole = 'operator' | 'supervisor' | 'admin';

interface User {
  id: string;
  email: string;
  name: string;
  role: UserRole;
}

interface AuthContextValue {
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

const AuthContext = createContext<AuthContextValue | null>(null);

const TOKEN_KEY = 'auth_token';
const USER_KEY = 'auth_user';

interface AuthProviderProps {
  children: ReactNode;
}

/**
 * Auth Provider
 *
 * Manages authentication state per F6 state ownership rules.
 * - Token stored in localStorage
 * - User info stored in localStorage (denormalized)
 * - Role defaults to 'operator' if unknown (safest default)
 */
export function AuthProvider({ children }: AuthProviderProps) {
  const [isLoading, setIsLoading] = useState(true);
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);

  // Initialize from localStorage on mount
  useEffect(() => {
    const storedToken = localStorage.getItem(TOKEN_KEY);
    const storedUser = localStorage.getItem(USER_KEY);

    if (storedToken && storedUser) {
      try {
        const parsedUser = JSON.parse(storedUser) as User;
        setToken(storedToken);
        setUser(parsedUser);
      } catch {
        // Invalid stored data - clear it
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
      }
    }

    setIsLoading(false);
  }, []);

  const login = useCallback((newToken: string, newUser: User) => {
    localStorage.setItem(TOKEN_KEY, newToken);
    localStorage.setItem(USER_KEY, JSON.stringify(newUser));
    setToken(newToken);
    setUser(newUser);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
  }, []);

  const getToken = useCallback(() => token, [token]);

  const value: AuthContextValue = {
    isAuthenticated: !!token,
    user,
    // TODO: Revert to 'operator' after authentication is implemented
    // Default to 'admin' during development to show all features
    role: user?.role ?? 'admin', // Default to admin for development (was 'operator')
    isLoading,
    login,
    logout,
    getToken,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

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
