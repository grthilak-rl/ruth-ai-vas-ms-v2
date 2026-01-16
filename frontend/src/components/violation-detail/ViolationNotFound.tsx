import { Link } from 'react-router-dom';
import './ViolationNotFound.css';

/**
 * Violation Not Found Component (F4 §6.3)
 *
 * Displayed when a violation ID is invalid or the violation
 * no longer exists. Provides clear navigation back to alerts.
 *
 * Per F3 Constraints:
 * - No technical IDs shown to user
 * - No error codes
 * - Clear, actionable message
 */
export function ViolationNotFound() {
  return (
    <div className="violation-not-found">
      <div className="violation-not-found__content">
        <h1 className="violation-not-found__title">
          Violation Not Found
        </h1>
        <p className="violation-not-found__message">
          This violation may have been removed or the link is incorrect.
        </p>
        <Link to="/alerts" className="violation-not-found__link">
          Back to Violations
        </Link>
      </div>
    </div>
  );
}
