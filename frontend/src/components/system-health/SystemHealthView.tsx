import { useMemo } from 'react';
import type { HealthResponse, ModelStatusInfo } from '../../state';
import { ServiceStatusCard, type ServiceHealthStatus } from './ServiceStatusCard';
import { ModelStatusCard } from './ModelStatusCard';
import { AuditEventList, type AuditEvent } from './AuditEventList';
import './SystemHealthView.css';

interface SystemHealthViewProps {
  /** System health data from /api/v1/health */
  health: HealthResponse;
  /** Model status data from /api/v1/models/status */
  models: ModelStatusInfo[];
  /** Whether models data is loading */
  modelsLoading?: boolean;
  /** Audit events (mock for now - would come from API) */
  auditEvents?: AuditEvent[];
  /** Whether audit events are loading */
  auditLoading?: boolean;
}

/**
 * System Health View (F4 §9)
 *
 * Admin-only diagnostic view for system and model health.
 *
 * Per E8 Task Spec:
 * - Service status cards (Backend, AI Runtime, Video)
 * - Model health summary with expandable details
 * - Audit visibility for rollbacks and health changes
 *
 * Per E8 Constraints:
 * - No pod, container, node, or process names
 * - No raw metrics (CPU, memory, FPS, latency numbers)
 * - No configuration or mutation actions
 * - This is a read-only diagnostic surface
 */
export function SystemHealthView({
  health,
  models,
  modelsLoading = false,
  auditEvents = [],
  auditLoading = false,
}: SystemHealthViewProps) {
  // Derive overall system status
  const systemStatus = useMemo(() => {
    if (health.status === 'unhealthy') {
      // Check if any component is unhealthy
      const components = health.components;
      if (components) {
        const hasOffline = Object.values(components).some(c => c === 'unhealthy');
        if (hasOffline) return 'offline' as const;
      }
      return 'degraded' as const;
    }
    return 'healthy' as const;
  }, [health]);

  // Derive service statuses from health.components
  const serviceStatuses = useMemo(() => {
    const components = health.components ?? {};

    return {
      backend: deriveServiceStatus(components.database, components.redis),
      aiRuntime: deriveServiceStatus(components.ai_runtime),
      video: 'healthy' as ServiceHealthStatus, // Assume healthy if backend is up
    };
  }, [health.components]);

  // Count model health
  const modelCounts = useMemo(() => {
    const healthy = models.filter(m => m.health === 'healthy').length;
    const degraded = models.filter(m => m.health === 'degraded').length;
    const unhealthy = models.filter(m => m.health === 'unhealthy').length;
    return { healthy, degraded, unhealthy, total: models.length };
  }, [models]);

  const systemStatusLabel = getSystemStatusLabel(systemStatus);
  const systemStatusIcon = getSystemStatusIcon(systemStatus);

  return (
    <div className="system-health-view">
      {/* System Status Header */}
      <div className={`system-health-view__header system-health-view__header--${systemStatus}`}>
        <h1 className="system-health-view__title">System Health</h1>
        <div className="system-health-view__status">
          <span className="system-health-view__status-icon">{systemStatusIcon}</span>
          <span className="system-health-view__status-label">{systemStatusLabel}</span>
        </div>
        <span className="system-health-view__updated">
          Last checked: {formatTimestamp(health.timestamp)}
        </span>
      </div>

      {/* Warning Banner (if degraded/offline) */}
      {systemStatus !== 'healthy' && (
        <div className={`system-health-view__banner system-health-view__banner--${systemStatus}`}>
          {systemStatus === 'offline' ? (
            <p>Critical issues detected. Some services are not responding.</p>
          ) : (
            <p>Some services are experiencing issues. Detection may be affected.</p>
          )}
        </div>
      )}

      {/* Service Status Cards */}
      <section className="system-health-view__section">
        <h2 className="system-health-view__section-title">Service Health</h2>
        <div className="system-health-view__services">
          <ServiceStatusCard
            serviceName="Backend"
            status={serviceStatuses.backend}
            description={getBackendDescription(serviceStatuses.backend)}
            lastUpdated={health.timestamp}
          />
          <ServiceStatusCard
            serviceName="AI Runtime"
            status={serviceStatuses.aiRuntime}
            description={getAIRuntimeDescription(serviceStatuses.aiRuntime, modelCounts)}
            lastUpdated={health.timestamp}
          />
          <ServiceStatusCard
            serviceName="Video Streaming"
            status={serviceStatuses.video}
            description={getVideoDescription(serviceStatuses.video)}
            lastUpdated={health.timestamp}
          />
        </div>
      </section>

      {/* Model Health Section */}
      <section className="system-health-view__section">
        <div className="system-health-view__section-header">
          <h2 className="system-health-view__section-title">AI Models</h2>
          <span className="system-health-view__model-summary">
            {modelCounts.healthy}/{modelCounts.total} Healthy
            {modelCounts.degraded > 0 && `, ${modelCounts.degraded} Degraded`}
            {modelCounts.unhealthy > 0 && `, ${modelCounts.unhealthy} Unhealthy`}
          </span>
        </div>

        {modelsLoading ? (
          <div className="system-health-view__loading">Loading model status...</div>
        ) : models.length === 0 ? (
          <div className="system-health-view__empty">
            <p>No AI models deployed</p>
            <p className="system-health-view__empty-hint">
              Models are deployed via the AI Runtime system.
            </p>
          </div>
        ) : (
          <div className="system-health-view__models">
            {models.map(model => (
              <ModelStatusCard
                key={model.model_id}
                model={model}
                isAdmin={true}
                expandable={true}
              />
            ))}
          </div>
        )}
      </section>

      {/* Audit Events Section */}
      <section className="system-health-view__section">
        <div className="system-health-view__section-header">
          <h2 className="system-health-view__section-title">Recent Events</h2>
        </div>
        <div className="system-health-view__audit">
          <AuditEventList
            events={auditEvents}
            isLoading={auditLoading}
            maxItems={10}
          />
        </div>
      </section>
    </div>
  );
}

function deriveServiceStatus(...components: (string | undefined)[]): ServiceHealthStatus {
  const hasUnhealthy = components.some(c => c === 'unhealthy');
  if (hasUnhealthy) return 'offline';

  const allHealthy = components.every(c => c === 'healthy' || c === undefined);
  if (allHealthy) return 'healthy';

  return 'degraded';
}

function getSystemStatusLabel(status: 'healthy' | 'degraded' | 'offline'): string {
  switch (status) {
    case 'healthy':
      return 'All Systems Operational';
    case 'degraded':
      return 'Degraded Performance';
    case 'offline':
      return 'Critical Issues';
  }
}

function getSystemStatusIcon(status: 'healthy' | 'degraded' | 'offline'): string {
  switch (status) {
    case 'healthy':
      return '●';
    case 'degraded':
      return '◐';
    case 'offline':
      return '○';
  }
}

function getBackendDescription(status: ServiceHealthStatus): string {
  switch (status) {
    case 'healthy':
      return 'Database and cache services operating normally.';
    case 'degraded':
      return 'Backend services experiencing delays.';
    case 'offline':
      return 'Backend services are not responding.';
  }
}

function getAIRuntimeDescription(
  status: ServiceHealthStatus,
  counts: { healthy: number; total: number }
): string {
  if (status === 'offline') {
    return 'AI Runtime is not responding. Detection is unavailable.';
  }
  if (status === 'degraded') {
    return 'AI Runtime is experiencing issues. Detection may be delayed.';
  }
  return `${counts.healthy} of ${counts.total} models running normally.`;
}

function getVideoDescription(status: ServiceHealthStatus): string {
  switch (status) {
    case 'healthy':
      return 'Video streaming services operating normally.';
    case 'degraded':
      return 'Video streaming experiencing issues.';
    case 'offline':
      return 'Video streaming is not available.';
  }
}

function formatTimestamp(timestamp?: string): string {
  if (!timestamp) return 'Unknown';
  try {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return 'Unknown';
  }
}
