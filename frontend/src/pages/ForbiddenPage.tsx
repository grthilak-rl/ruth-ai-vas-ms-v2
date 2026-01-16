import { Link } from 'react-router-dom';
import './ForbiddenPage.css';

/**
 * 403 Forbidden Page (E11)
 *
 * Friendly access denied screen for unauthorized route access.
 *
 * Per F2 §Permission Enforcement:
 * - Deep link to forbidden screen → 403 with "Contact Admin" message
 *
 * Per E11 constraints:
 * - Neutral, non-alarming language (no "access denied")
 * - Never blame the operator
 * - Provide clear escape: "Go to Dashboard"
 * - Do not expose role or permission details
 */
export function ForbiddenPage() {
  return (
    <div className="forbidden-page">
      <div className="forbidden-page__content">
        <div className="forbidden-page__icon" aria-hidden="true">
          <svg
            width="64"
            height="64"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <path d="M12 8v4" />
            <path d="M12 16h.01" />
          </svg>
        </div>

        <h1 className="forbidden-page__title">Page Not Available</h1>

        <p className="forbidden-page__message">
          This page requires additional permissions. Please contact your
          administrator if you need access.
        </p>

        <div className="forbidden-page__actions">
          <Link to="/" className="forbidden-page__button">
            Go to Dashboard
          </Link>
        </div>
      </div>
    </div>
  );
}
