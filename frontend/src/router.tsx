import { createBrowserRouter } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { RequireSupervisor, RequireAdmin } from './components/guards';
import {
  OverviewPage,
  AlertsPage,
  AlertDetailPage,
  CamerasPage,
  CameraDetailPage,
  CameraFullscreenPageWrapper,
  AnalyticsPage,
  CameraPerformancePage,
  ExportDataPage,
  SettingsPage,
  SystemHealthPage,
  ModelStatusPage,
  ForbiddenPage,
} from './pages';

/**
 * Application Router (E11 Role-Protected)
 *
 * Routes aligned with F2 Information Architecture.
 *
 * Per F2 §Permission Enforcement:
 * - /analytics/* → Supervisor and Admin only
 * - /settings/* → Admin only
 * - /forbidden → 403 page for unauthorized access
 *
 * Role guards (RequireSupervisor, RequireAdmin) redirect to /forbidden
 * if the user lacks the required role.
 */
export const router = createBrowserRouter([
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

      // Settings section - Admin only
      {
        path: 'settings',
        element: (
          <RequireAdmin>
            <SettingsPage />
          </RequireAdmin>
        ),
      },
      {
        path: 'settings/health',
        element: (
          <RequireAdmin>
            <SystemHealthPage />
          </RequireAdmin>
        ),
      },
      {
        path: 'settings/models',
        element: (
          <RequireAdmin>
            <ModelStatusPage />
          </RequireAdmin>
        ),
      },

      // 403 Forbidden page (E11)
      {
        path: 'forbidden',
        element: <ForbiddenPage />,
      },
    ],
  },
]);
