import { NavLink } from 'react-router-dom';
import { useIsAdmin, useIsSupervisor } from '../../state';
import { SystemStatusIndicator } from './SystemStatusIndicator';
import { AlertsBadge } from './AlertsBadge';
import './TopNav.css';

/**
 * Top Navigation Bar (F2-aligned, E11 Role Gating)
 *
 * Navigation items (exact order per F2):
 * - Overview (All)
 * - Cameras (All)
 * - Violations (All) - with live badge, includes filtering for all statuses
 * - Analytics (Supervisor+)
 * - Settings (Admin only)
 *
 * Note: History page was removed as the Violations page now includes
 * comprehensive filtering (status, date range, camera) that covers
 * all historical violation search needs.
 *
 * Per F2 §Role-Based Visibility Summary:
 * - Operator: Overview, Cameras, Violations
 * - Supervisor: All Operator items + Analytics
 * - Admin: All Supervisor items + Settings
 *
 * Rules:
 * - Highlight active route
 * - Navigation MUST NOT depend on backend state
 * - Role gating is UI-only; backend enforces actual permissions
 */
export function TopNav() {
  // Per F2: Analytics visible for Supervisor+ role
  const canAccessAnalytics = useIsSupervisor();
  // Per F2: Settings visible only for Admin role
  const canAccessSettings = useIsAdmin();

  return (
    <header className="top-nav">
      <div className="top-nav__brand">
        <span className="top-nav__logo">Ruth AI</span>
      </div>

      <nav className="top-nav__links" role="navigation" aria-label="Main navigation">
        {/* Overview - All roles */}
        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            `top-nav__link ${isActive ? 'top-nav__link--active' : ''}`
          }
        >
          Overview
        </NavLink>

        {/* Camera Monitoring - All roles */}
        <NavLink
          to="/cameras"
          className={({ isActive }) =>
            `top-nav__link ${isActive ? 'top-nav__link--active' : ''}`
          }
        >
          Camera Monitoring
        </NavLink>

        {/* Violations - All roles (with badge) */}
        <NavLink
          to="/alerts"
          className={({ isActive }) =>
            `top-nav__link top-nav__link--with-badge ${isActive ? 'top-nav__link--active' : ''}`
          }
        >
          Violations
          <AlertsBadge />
        </NavLink>

        {/* Analytics - Supervisor and Admin only */}
        {canAccessAnalytics && (
          <NavLink
            to="/analytics"
            className={({ isActive }) =>
              `top-nav__link ${isActive ? 'top-nav__link--active' : ''}`
            }
          >
            Analytics
          </NavLink>
        )}

        {/* Settings - Admin only */}
        {canAccessSettings && (
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              `top-nav__link ${isActive ? 'top-nav__link--active' : ''}`
            }
          >
            Settings
          </NavLink>
        )}
      </nav>

      <div className="top-nav__status">
        <SystemStatusIndicator />
      </div>
    </header>
  );
}
