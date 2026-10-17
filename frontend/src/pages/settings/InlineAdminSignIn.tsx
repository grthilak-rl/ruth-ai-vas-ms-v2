import { useState, type FormEvent } from 'react';
import { AdminApiError, adminLogin } from '../admin/adminApi';
import { notifyAdminSessionChanged } from '../admin/useAdminSession';
import './InlineAdminSignIn.css';

/**
 * Sign in to the admin account without leaving the page.
 *
 * Settings is reachable by anyone and most of it works signed out. The
 * admin-only parts therefore ask for credentials *where the capability is*
 * rather than behind a route guard: navigating away to /admin/login and
 * back would lose the rest of the page, and a whole-page login would
 * suggest Settings itself is admin-only, which it is not.
 *
 * On success it notifies the admin-session store, which re-renders every
 * subscribed section in place. This component does not navigate.
 */

function signInErrorMessage(error: unknown): string {
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

export interface InlineAdminSignInProps {
  /** What signing in would unlock, e.g. "upload or manage models". */
  capability: string;
  /** Rendered above the form when a session just expired. */
  expired?: boolean;
}

export function InlineAdminSignIn({ capability, expired = false }: InlineAdminSignInProps) {
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
      // Re-renders every section subscribed to the admin session. No
      // navigation: the operator stays exactly where they were.
      notifyAdminSessionChanged();
    } catch (err) {
      setError(signInErrorMessage(err));
      setPassword('');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="inline-signin" onSubmit={handleSubmit} noValidate>
      <p className="inline-signin__prompt">
        <span className="inline-signin__lock" aria-hidden="true">
          &#128274;
        </span>
        {expired
          ? `Your admin session expired. Sign in again to ${capability}.`
          : `Sign in as administrator to ${capability}.`}
      </p>

      <div className="inline-signin__fields">
        <label className="inline-signin__field">
          <span className="inline-signin__label">Username</span>
          <input
            className="inline-signin__input"
            type="text"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </label>

        <label className="inline-signin__field">
          <span className="inline-signin__label">Password</span>
          <input
            className="inline-signin__input"
            type="password"
            name="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>

        <button
          className="inline-signin__submit"
          type="submit"
          disabled={submitting || !username.trim() || !password}
        >
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </div>

      {error && (
        <p className="inline-signin__error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
