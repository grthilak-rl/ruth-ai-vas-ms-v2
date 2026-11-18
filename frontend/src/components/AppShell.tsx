import { Outlet } from 'react-router-dom';
import { useHealthCheck } from '../hooks/useHealthCheck';
import { TopNav } from './navigation';
import { OfflineBanner } from './ui';
import { ProjectBanner } from './project/ProjectBanner';
import { ProjectViewProvider } from '../state/project/ProjectViewContext';
import { useProjectView } from '../state/project/projectView';

/**
 * The routed page, remounted whenever the viewed project changes. Pages that
 * keep their own fetched state (Analytics) then start over under the new
 * project instead of showing the previous project's numbers.
 */
function ProjectOutlet() {
  const { viewedSlug } = useProjectView();
  return <Outlet key={viewedSlug ?? 'current'} />;
}

/**
 * Global Application Shell (E4, E9)
 *
 * Top-level layout containing:
 * - Top navigation bar with system status (F2, F4)
 * - Route outlet for page content
 * - Global offline banner (E9)
 * - Project view mode: the past-project banner and the provider every
 *   page reads the viewed project from (state/project/)
 *
 * Per F2: Navigation MUST NOT depend on backend state.
 * Per E9: Global offline awareness with auto-recovery.
 */
export function AppShell() {
  // Perform health check on app load (logs to console only)
  useHealthCheck();

  return (
    <ProjectViewProvider>
      <div className="app-shell">
        <TopNav />
        <ProjectBanner />
        <main className="app-main">
          <ProjectOutlet />
        </main>
        {/* Global offline indicator (E9) */}
        <OfflineBanner />
      </div>
    </ProjectViewProvider>
  );
}
