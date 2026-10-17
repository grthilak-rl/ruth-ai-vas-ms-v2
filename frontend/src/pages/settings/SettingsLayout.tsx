import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { setSessionExpiredHandler } from '../admin/adminApi';
import { notifyAdminSessionChanged, useAdminSession } from '../admin/useAdminSession';
import './SettingsLayout.css';

/**
 * Settings — one page, three tabs.
 *
 * Replaces the two-card Settings hub AND the separate Model Management
 * area, which between them showed uploaded models twice (each view holding
 * half the truth) and put the only entry point to project archiving behind
 * a nav item of its own.
 *
 * Tabs are routes, so every tab is linkable, bookmarkable and survives a
 * refresh. The page is reachable without signing in; individual sections
 * ask for the admin token where they need it — see InlineAdminSignIn.
 *
 * Nothing here consults the app's role context. `useIsAdmin()` currently
 * returns true for everyone (AuthContext defaults the role to 'admin' with
 * a TODO, and nothing ever calls login()), so gating on it would be
 * security theatre that silently inverts the day real auth lands. The
 * admin token is the only real capability signal.
 */

const TABS = [
  { to: '/settings/models', label: 'AI Models' },
  { to: '/settings/project', label: 'Project' },
  { to: '/settings/system', label: 'System' },
] as const;

export function SettingsLayout() {
  const { isSignedIn, signOut } = useAdminSession();

  // Set once for the whole Settings area: a 401 from any admin call must
  // flip the affected section to its signed-out state in place, instead of
  // the default hard redirect to /admin/login, which would throw the
  // operator out of a page that is mostly usable signed out.
  const [sessionExpired, setSessionExpired] = useState(false);
  useEffect(() => {
    setSessionExpiredHandler(() => {
      setSessionExpired(true);
      notifyAdminSessionChanged();
    });
    return () => setSessionExpiredHandler(null);
  }, []);

  // Clear the expiry notice once a session exists again, so it does not
  // linger above a section that is now working.
  useEffect(() => {
    if (isSignedIn) setSessionExpired(false);
  }, [isSignedIn]);

  return (
    <div className="settings-layout">
      <header className="settings-layout__header">
        <div>
          <h1 className="settings-layout__title">Settings</h1>
          <p className="settings-layout__subtitle">
            AI models, project lifecycle and system diagnostics
          </p>
        </div>
        {isSignedIn && (
          <div className="settings-layout__session">
            <span className="settings-layout__session-label">Signed in as administrator</span>
            <button
              className="settings-layout__signout"
              type="button"
              onClick={signOut}
            >
              Sign out
            </button>
          </div>
        )}
      </header>

      <nav className="settings-layout__tabs" aria-label="Settings sections">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) =>
              `settings-layout__tab ${isActive ? 'settings-layout__tab--active' : ''}`
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      <div className="settings-layout__content">
        {/* `sessionExpired` reaches the tabs through context-free props via
            the router outlet; each tab decides whether to mention it. */}
        <Outlet context={{ sessionExpired }} />
      </div>
    </div>
  );
}

/** Shape passed down through the router outlet to each tab. */
export interface SettingsOutletContext {
  /** True when an admin call was rejected since the page loaded. */
  sessionExpired: boolean;
}
