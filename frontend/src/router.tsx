import { Navigate, createBrowserRouter, useParams } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { RequireSupervisor } from './components/guards';
import {
  OverviewPage,
  AlertsPage,
  AlertDetailPage,
  CamerasPage,
  CameraDetailPage,
  CameraFullscreenPageWrapper,
  ViewingPanePage,
  BookmarkMonitoringPage,
  AnalyticsPage,
  CameraPerformancePage,
  ExportDataPage,
  SettingsLayout,
  SettingsModelsTab,
  SettingsProjectTab,
  SettingsSystemTab,
  ForbiddenPage,
} from './pages';
import { AdminLogin, ModelDetailPage, RequireAdminToken } from './pages/admin';

/**
 * /admin/models/:modelPk -> /settings/models/:modelPk
 *
 * A component rather than a static redirect because the param has to be
 * carried across; a plain <Navigate to="/settings/models"> would silently
 * drop which model the link pointed at.
 */
function RedirectModelDetail() {
  const { modelPk = '' } = useParams();
  return <Navigate to={`/settings/models/${modelPk}`} replace />;
}

/**
 * Application Router (E11 Role-Protected)
 *
 * Routes aligned with F2 Information Architecture.
 *
 * Per F2 §Permission Enforcement:
 * - /analytics/* → Supervisor and Admin only
 * - /settings/* → open; admin sections sign in inline (admin token)
 * - /forbidden → 403 page for unauthorized access
 *
 * Role guards (RequireSupervisor) redirect to /forbidden
 * if the user lacks the required role.
 */
export const router = createBrowserRouter([
  // Viewing Pane — deliberately OUTSIDE the AppShell layout.
  //
  // The wall display must render feeds edge to edge with no nav, header or
  // page padding, so it cannot be a child of AppShell. Being a real route
  // (rather than an overlay on /cameras) also means it can be bookmarked or
  // used as a kiosk homepage, so the display restores itself after a reboot.
  {
    path: '/cameras/viewing-pane',
    element: <ViewingPanePage />,
  },
  {
    path: '/',
    element: <AppShell />,
    children: [
      // Overview (default landing) - All roles
      {
        index: true,
        element: <OverviewPage />,
      },

      // Alerts section - All roles
      {
        path: 'alerts',
        element: <AlertsPage />,
      },
      {
        path: 'alerts/:id',
        element: <AlertDetailPage />,
      },

      // Cameras section - All roles
      {
        path: 'cameras',
        element: <CamerasPage />,
      },
      {
        path: 'cameras/fullscreen/:id',
        element: <CameraFullscreenPageWrapper />,
      },
      {
        path: 'cameras/:id',
        element: <CameraDetailPage />,
      },

      // Bookmark Monitoring - All roles (D.6)
      // Replaces the prior /bookmark-analyses pages; those page
      // components are dead code (file kept, route removed) and
      // a follow-up cleanup pass deletes the backend job machinery.
      {
        path: 'bookmark-monitoring',
        element: <BookmarkMonitoringPage />,
      },

      // Analytics section - Supervisor and Admin only
      {
        path: 'analytics',
        element: (
          <RequireSupervisor>
            <AnalyticsPage />
          </RequireSupervisor>
        ),
      },
      {
        path: 'analytics/cameras',
        element: (
          <RequireSupervisor>
            <CameraPerformancePage />
          </RequireSupervisor>
        ),
      },
      {
        path: 'analytics/export',
        element: (
          <RequireSupervisor>
            <ExportDataPage />
          </RequireSupervisor>
        ),
      },

      // Settings - open to everyone; individual sections ask for the
      // admin token inline. Deliberately NOT role-gated: the role in
      // AuthContext is hardcoded to 'admin' with a TODO and nothing ever
      // calls login(), so a role gate protects nothing today and would
      // hide the whole page the moment real auth lands. Capability comes
      // from the admin token alone (useAdminSession).
      {
        path: 'settings',
        element: <SettingsLayout />,
        children: [
          { index: true, element: <Navigate to="/settings/models" replace /> },
          { path: 'models', element: <SettingsModelsTab /> },
          {
            // Drill-down from the uploaded-models list. Keeps its route
            // guard: unlike the tabs, it is nothing but admin content.
            path: 'models/:modelPk',
            element: (
              <RequireAdminToken>
                <ModelDetailPage />
              </RequireAdminToken>
            ),
          },
          { path: 'project', element: <SettingsProjectTab /> },
          { path: 'system', element: <SettingsSystemTab /> },
          // Old sub-page path.
          { path: 'health', element: <Navigate to="/settings/system" replace /> },
        ],
      },

      // 403 Forbidden page (E11)
      {
        path: 'forbidden',
        element: <ForbiddenPage />,
      },

      // The admin area moved into Settings. The login page stays (it is
      // still the redirect target for deep links and for a 401 raised
      // outside Settings); everything else redirects, so links already in
      // the wild keep working.
      {
        path: 'admin/login',
        element: <AdminLogin />,
      },
      {
        path: 'admin/models',
        element: <Navigate to="/settings/models" replace />,
      },
      {
        path: 'admin/models/:modelPk',
        element: <RedirectModelDetail />,
      },
      {
        path: 'admin/projects',
        element: <Navigate to="/settings/project" replace />,
      },
    ],
  },
]);
