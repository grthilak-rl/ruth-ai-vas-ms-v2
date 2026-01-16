import { useMemo } from 'react';
import { Navigate } from 'react-router-dom';
import {
  useHealthQuery,
  useModelsStatusQuery,
  useIsAdmin,
} from '../../state';
import {
  SystemHealthView,
  SystemHealthSkeleton,
  type AuditEvent,
} from '../../components/system-health';

/**
 * System Health Page (F2 Path: /settings/health)
 *
 * Admin-only diagnostic view for system and model health.
 *
 * Per F4 §9:
 * - Service status cards (Backend, AI Runtime, Video)
 * - Model health summary
 * - Audit visibility for rollbacks and health changes
 *
 * Per E8 Constraints:
 * - Only visible to Admin role
 * - No pod, container, node, or process names
 * - No raw metrics
 * - Read-only diagnostic surface
 */
export function SystemHealthPage() {
  const isAdmin = useIsAdmin();

  // If not admin, redirect to overview
  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  return <SystemHealthContent />;
}

function SystemHealthContent() {
  const {
    data: health,
    isLoading: isHealthLoading,
    isError: isHealthError,
    refetch: refetchHealth,
  } = useHealthQuery();

  const {
    data: modelsData,
    isLoading: isModelsLoading,
  } = useModelsStatusQuery();

  // Generate mock audit events (in production, this would come from API)
  const auditEvents = useMemo<AuditEvent[]>(() => {
    return generateMockAuditEvents();
  }, []);

  // Loading state
  if (isHealthLoading) {
    return <SystemHealthSkeleton />;
  }

  // Error state
  if (isHealthError || !health) {
    return (
      <div className="page-container">
        <div className="error-state">
          <h1>System Health</h1>
          <p>Unable to load system health data.</p>
          <button onClick={() => refetchHealth()}>Retry</button>
        </div>
      </div>
    );
  }

  return (
    <SystemHealthView
      health={health}
      models={modelsData?.models ?? []}
      modelsLoading={isModelsLoading}
      auditEvents={auditEvents}
      auditLoading={false}
    />
  );
}

/**
 * Generate mock audit events for demonstration.
 * In production, these would come from an API endpoint.
 */
function generateMockAuditEvents(): AuditEvent[] {
  const now = new Date();

  return [
    {
      id: '1',
      type: 'system_startup',
      timestamp: new Date(now.getTime() - 8 * 60 * 60 * 1000).toISOString(), // 8 hours ago
      message: 'System startup completed',
      details: 'All services initialized successfully',
    },
    {
      id: '2',
      type: 'model_upgrade',
      timestamp: new Date(now.getTime() - 6 * 60 * 60 * 1000).toISOString(), // 6 hours ago
      message: 'Fall Detection model updated',
      details: 'Updated to latest version',
    },
    {
      id: '3',
      type: 'system_recovery',
      timestamp: new Date(now.getTime() - 2 * 60 * 60 * 1000).toISOString(), // 2 hours ago
      message: 'System recovered from degraded state',
      details: 'AI Runtime latency returned to normal',
    },
  ];
}
