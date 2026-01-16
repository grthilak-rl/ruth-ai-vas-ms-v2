import { Link, Navigate } from 'react-router-dom';
import { useIsAdmin } from '../../state';
import './SettingsPage.css';

/**
 * Settings Page
 * F2 Path: /settings
 *
 * Admin settings hub with links to sub-sections:
 * - System Health (/settings/health)
 * - Model Status (/settings/models)
 */
export function SettingsPage() {
  const isAdmin = useIsAdmin();

  // If not admin, redirect to overview
  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="settings-page">
      <header className="settings-page__header">
        <h1 className="settings-page__title">Settings</h1>
        <p className="settings-page__subtitle">System administration and diagnostics</p>
      </header>

      <div className="settings-page__content">
        <div className="settings-page__cards">
          {/* System Health Card */}
          <Link to="/settings/health" className="settings-card">
            <div className="settings-card__icon">
              <span aria-hidden="true">●</span>
            </div>
            <div className="settings-card__content">
              <h2 className="settings-card__title">System Health</h2>
              <p className="settings-card__description">
                View service status, component health, and system diagnostics.
                Monitor Database, Redis, AI Runtime, and Video Streaming services.
              </p>
            </div>
            <span className="settings-card__arrow" aria-hidden="true">&rarr;</span>
          </Link>

          {/* Model Status Card */}
          <Link to="/settings/models" className="settings-card">
            <div className="settings-card__icon">
              <span aria-hidden="true">AI</span>
            </div>
            <div className="settings-card__content">
              <h2 className="settings-card__title">AI Models</h2>
              <p className="settings-card__description">
                View deployed AI model status, versions, and health.
                Monitor model performance and active cameras.
              </p>
            </div>
            <span className="settings-card__arrow" aria-hidden="true">&rarr;</span>
          </Link>
        </div>
      </div>
    </div>
  );
}
