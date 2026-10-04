import { useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AdminApiError, adminLogin, safeNextPath } from './adminApi';
import './AdminPages.css';

function loginErrorMessage(error: unknown): string {
  if (!(error instanceof AdminApiError)) {
    return 'Sign-in failed. Please try again.';
  }
  switch (error.status) {
    case 401:
      return 'Invalid username or password.';
    case 429: {
      const minutes = Math.max(1, Math.ceil((error.retryAfterSeconds ?? 900) / 60));
      return `Too many failed attempts. Try again in ${minutes} minute${minutes === 1 ? '' : 's'}.`;
    }
    case 503:
      return 'Admin sign-in is not configured on this server.';
    case 0:
      return 'Unable to reach the server.';
    default:
      return 'Sign-in failed. Please try again.';
  }
}

/**
 * Admin Login
 * Path: /admin/login
 *
 * Signs in to the admin area (Model Management) with the server-side admin
 * account. Independent of the app's role context.
 */
export function AdminLogin() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await adminLogin(username.trim(), password);
      navigate(safeNextPath(searchParams.get('next')), { replace: true });
    } catch (err) {
      setError(loginErrorMessage(err));
      setPassword('');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="admin-page admin-page--centered">
      <form className="admin-card admin-login" onSubmit={handleSubmit} noValidate>
        <h1 className="admin-card__title">Admin sign-in</h1>
        <p className="admin-card__subtitle">Model Management requires an admin account.</p>

        <label className="admin-field">
          <span className="admin-field__label">Username</span>
          <input
            className="admin-field__input"
            type="text"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoFocus
          />
        </label>

        <label className="admin-field">
          <span className="admin-field__label">Password</span>
          <input
            className="admin-field__input"
            type="password"
            name="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>

        {error && (
          <p className="admin-login__error" role="alert">
            {error}
          </p>
        )}

        <button
          className="admin-button"
          type="submit"
          disabled={submitting || !username.trim() || !password}
        >
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
