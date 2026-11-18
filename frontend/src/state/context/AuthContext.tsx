import { useState, useCallback, type ReactNode } from 'react';
import { AuthContext, TOKEN_KEY, USER_KEY, type AuthContextValue, type User } from './auth';

function readStoredSession(): { token: string | null; user: User | null } {
  try {
    const storedToken = localStorage.getItem(TOKEN_KEY);
    const storedUser = localStorage.getItem(USER_KEY);
    if (storedToken && storedUser) {
      return { token: storedToken, user: JSON.parse(storedUser) as User };
    }
  } catch {
    // Invalid stored data (or storage blocked) - clear it
    try {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    } catch {
      /* storage blocked */
    }
  }
  return { token: null, user: null };
}

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
  // Read the stored session once, while the first render's state is set
  // up, instead of in an effect that renders twice.
  const [stored] = useState(readStoredSession);
  const [token, setToken] = useState<string | null>(stored.token);
  const [user, setUser] = useState<User | null>(stored.user);
  const isLoading = false;

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
