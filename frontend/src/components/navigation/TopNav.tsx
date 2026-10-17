import { NavLink } from 'react-router-dom';
import { useIsSupervisor } from '../../state';
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
 * - Settings (everyone; admin-only sections sign in inline)
 *
 * Note: History page was removed as the Violations page now includes
 * comprehensive filtering (status, date range, camera) that covers
 * all historical violation search needs.
 *
 * Per F2 §Role-Based Visibility Summary:
 * - Operator: Overview, Cameras, Violations
 * - Supervisor: All Operator items + Analytics
 *
 * Settings is deliberately NOT role-gated. It used to be hidden behind
 * useIsAdmin(), which returns true for everybody — AuthContext hardcodes
 * the role to 'admin' with a TODO and nothing ever calls login() — so the
 * gate did nothing except promise to hide the page the day real auth
 * arrives. The page itself is safe to show: its open tabs read only
 * endpoints that need no credentials, and everything that mutates asks
 * for the admin token inline.
 *
 * The separate "Model Management" item is gone; that page is now the
 * AI Models tab of Settings.
 *
 * Rules:
 * - Highlight active route
 * - Navigation MUST NOT depend on backend state
 * - Role gating is UI-only; backend enforces actual permissions
 */
export function TopNav() {
  // Per F2: Analytics visible for Supervisor+ role
  const canAccessAnalytics = useIsSupervisor();

  return (
    <header className="top-nav">
      <div className="top-nav__brand">
        <img src="/visics_logo.jpeg" alt="Visics" className="top-nav__logo" />
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

        {/* Bookmark Monitoring - All roles (D.6) */}
        <NavLink
          to="/bookmark-monitoring"
          className={({ isActive }) =>
            `top-nav__link ${isActive ? 'top-nav__link--active' : ''}`
          }
        >
          Bookmark Monitoring
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

        {/* Settings - everyone; admin sections sign in inline */}
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `top-nav__link ${isActive ? 'top-nav__link--active' : ''}`
          }
        >
          Settings
        </NavLink>
      </nav>

      <div className="top-nav__status">
        <SystemStatusIndicator />
      </div>
    </header>
  );
}
