import { useMemo } from 'react';
import type { Device, HealthResponse, ModelStatusInfo } from '../../state';
import { formatUptime } from '../../state';
import { ServiceStatusCard, type ServiceHealthStatus } from './ServiceStatusCard';
import { MonitoringCoverage } from './MonitoringCoverage';
import { CameraFeeds } from './CameraFeeds';
import {
  deriveStoreRuntimeStatus,
  getModelStoreDescription,
} from './storeRuntimeStatus';
import { ModelStatusCard } from './ModelStatusCard';
import './SystemHealthView.css';

interface SystemHealthViewProps {
  /** System health data from /api/v1/health */
  health: HealthResponse;
  /** Model status data from /api/v1/models/status */
  models: ModelStatusInfo[];
  /** Whether models data is loading */
  modelsLoading?: boolean;
  /** Cameras, for the monitoring-coverage signal (BL-11). */
  devices?: Device[];
  /** Whether the devices list is loading */
  devicesLoading?: boolean;
  /** Callback to refresh health data */
  onRefresh?: () => void;
  /** Whether health data is currently refreshing */
  isRefreshing?: boolean;
}

/**
 * System Health View (F4 §9) - Enhanced
 *
 * Admin-only diagnostic view for system and model health.
 *
 * Features:
 * - Service status cards with expandable detailed metrics
 * - Model health summary with expandable details
 * - Manual refresh button
 * - System uptime display
 *
 * Per E8 Constraints:
 * - No pod, container, node, or process names
 * - Human-readable descriptions
 * - This is a read-only diagnostic surface
 */
export function SystemHealthView({
  health,
  models,
  modelsLoading = false,
  devices = [],
  devicesLoading = false,
  onRefresh,
  isRefreshing = false,
}: SystemHealthViewProps) {
  // Derive overall system status
  const systemStatus = useMemo(() => {
    if (health.status === 'unhealthy') {
      // Check if any component is unhealthy
      const components = health.components;
      if (components) {
        const hasOffline = Object.values(components).some(c => c?.status === 'unhealthy');
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
      backend: deriveServiceStatus(components.database?.status, components.redis?.status),
      aiRuntime: deriveServiceStatus(components.ai_runtime?.status),
      video: deriveServiceStatus(components.vas?.status),
      nlpChat: deriveServiceStatus(components.nlp_chat?.status),
      // Unreachable is reported by the backend as `degraded` so it cannot
      // flip overall health to unhealthy — but on the card it is a hard
      // failure, not a wobble, so it renders red. See storeRuntimeStatus.
      modelStore: deriveStoreRuntimeStatus(components.model_store_runtime),
    };
  }, [health.components]);

  // Count model health.
  //
  // Two counts, because the two places they appear mean different things.
  // /models/status returns built-in AND uploaded (store) models in one
  // array, store ones marked source:'store'.
  const countHealth = (list: ModelStatusInfo[]) => ({
    healthy: list.filter(m => m.health === 'healthy').length,
    degraded: list.filter(m => m.health === 'degraded').length,
    unhealthy: list.filter(m => m.health === 'unhealthy').length,
    total: list.length,
  });

  // The "AI Models" section below lists every model, so its header counts
  // every model.
  const modelCounts = useMemo(() => countHealth(models), [models]);

  // The AI Runtime service card must count ONLY built-in models. Uploaded
  // models are served by a different process with its own card on this
  // page, so including them made the card claim credit for models the AI
  // Runtime has never loaded ("8 of 8" when it serves 5).
  const builtInCounts = useMemo(
    () => countHealth(models.filter(m => m.source !== 'store')),
    [models]
  );

  const systemStatusLabel = getSystemStatusLabel(systemStatus);
  const systemStatusIcon = getSystemStatusIcon(systemStatus);
  const uptimeDisplay = formatUptime(health.uptime_seconds);

  return (
    <div className="system-health-view">
      {/* System Status Header */}
      <div className={`system-health-view__header system-health-view__header--${systemStatus}`}>
        <h1 className="system-health-view__title">System Health</h1>
        <div className="system-health-view__status">
          <span className="system-health-view__status-icon">{systemStatusIcon}</span>
          <span className="system-health-view__status-label">{systemStatusLabel}</span>
        </div>
        <div className="system-health-view__meta">
          {uptimeDisplay !== 'Unknown' && (
            <span className="system-health-view__uptime">
              Uptime: <strong>{uptimeDisplay}</strong>
            </span>
          )}
          <span className="system-health-view__updated">
            Last checked: {formatTimestamp(health.timestamp)}
          </span>
          {onRefresh && (
            <button
              className={`system-health-view__refresh-btn ${isRefreshing ? 'system-health-view__refresh-btn--loading' : ''}`}
              onClick={onRefresh}
              disabled={isRefreshing}
              title="Refresh health status"
              aria-label="Refresh health status"
            >
              <span className="system-health-view__refresh-icon">↻</span>
              {isRefreshing ? 'Checking...' : 'Refresh'}
            </button>
          )}
        </div>
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
      {/* Above the service cards on purpose: a degraded Redis is worth
          knowing, a camera nobody is watching is worth knowing first.
          See BL-11. */}
      {/* Feeds first: a camera with no video can't be monitored at all. */}
      <CameraFeeds devices={devices} isLoading={devicesLoading} />
      <MonitoringCoverage devices={devices} isLoading={devicesLoading} />

      <section className="system-health-view__section">
        <h2 className="system-health-view__section-title">Service Health</h2>
        <p className="system-health-view__section-hint">Click a card to expand detailed metrics</p>
        <div className="system-health-view__services">
          <ServiceStatusCard
            serviceName="Backend"
            status={serviceStatuses.backend}
            description={getBackendDescription(serviceStatuses.backend)}
            lastUpdated={health.timestamp}
            expandable={true}
            serviceType="backend"
            components={health.components}
          />
          <ServiceStatusCard
            serviceName="AI Runtime"
            status={serviceStatuses.aiRuntime}
            description={getAIRuntimeDescription(serviceStatuses.aiRuntime, builtInCounts)}
            lastUpdated={health.timestamp}
            expandable={true}
            serviceType="ai_runtime"
            components={health.components}
          />
          <ServiceStatusCard
            serviceName="Video Streaming"
            status={serviceStatuses.video}
            description={getVideoDescription(serviceStatuses.video)}
            lastUpdated={health.timestamp}
            expandable={true}
            serviceType="video"
            components={health.components}
          />
          <ServiceStatusCard
            serviceName="NLP Chat"
            status={serviceStatuses.nlpChat}
            description={getNLPChatDescription(serviceStatuses.nlpChat)}
            lastUpdated={health.timestamp}
            expandable={true}
            serviceType="nlp_chat"
            components={health.components}
          />
          {/* Only for deployments that run a store runtime. Absent (older
              backend) or "disabled" (MODEL_STORE_RUNTIME_URL unset) means
              there is nothing to report, so the card is not rendered. */}
          {health.components?.model_store_runtime &&
            health.components.model_store_runtime.status !== 'disabled' && (
              <ServiceStatusCard
                serviceName="Model store runtime"
                status={serviceStatuses.modelStore}
                description={getModelStoreDescription(
                  serviceStatuses.modelStore,
                  health.components.model_store_runtime
                )}
                lastUpdated={health.timestamp}
                expandable={true}
                serviceType="model_store_runtime"
                components={health.components}
              />
            )}
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
    </div>
  );
}

function deriveServiceStatus(...components: (string | undefined)[]): ServiceHealthStatus {
  const hasUnhealthy = components.some(c => c === 'unhealthy');
  if (hasUnhealthy) return 'offline';

  const hasDegraded = components.some(c => c === 'degraded');
  if (hasDegraded) return 'degraded';

  // If every contributing component is intentionally disabled (and nothing
  // else is reported), surface that — don't claim healthy. This is the
  // single-component case used for nlp_chat in this deployment.
  const reported = components.filter((c): c is string => Boolean(c));
  if (reported.length > 0 && reported.every(c => c === 'disabled')) {
    return 'disabled';
  }

  // 'disabled' from one of several backing components doesn't drag the
  // service down — treat it like undefined for the "all healthy" check.
  const allHealthyOrDisabled = components.every(
    c => c === 'healthy' || c === 'disabled' || c === undefined,
  );
  if (allHealthyOrDisabled) return 'healthy';

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
    case 'disabled':
      return 'Backend services intentionally disabled in this deployment.';
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
    case 'disabled':
      return 'Video streaming intentionally disabled in this deployment.';
  }
}

function getNLPChatDescription(status: ServiceHealthStatus): string {
  switch (status) {
    case 'healthy':
      return 'Natural language chat service and LLM operating normally.';
    case 'degraded':
      return 'Chat service experiencing issues. Responses may be delayed.';
    case 'offline':
      return 'Chat service is not available.';
    case 'disabled':
      return 'Chat service intentionally disabled in this deployment.';
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
