import { Outlet } from 'react-router-dom';
import { useHealthCheck } from '../hooks/useHealthCheck';
import { TopNav } from './navigation';
import { OfflineBanner } from './ui';

/**
 * Global Application Shell (E4, E9)
 *
 * Top-level layout containing:
 * - Top navigation bar with system status (F2, F4)
 * - Route outlet for page content
 * - Global offline banner (E9)
 *
 * Per F2: Navigation MUST NOT depend on backend state.
 * Per E9: Global offline awareness with auto-recovery.
 */
export function AppShell() {
  // Perform health check on app load (logs to console only)
  useHealthCheck();

  return (
    <div className="app-shell">
      <TopNav />
      <main className="app-main">
        <Outlet />
      </main>
      {/* Global offline indicator (E9) */}
      <OfflineBanner />
    </div>
  );
}
