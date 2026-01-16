import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  useHealthQuery,
  formatUptime,
  getTimeSinceLastCheck,
  getComponentDisplayName,
  useIsAdmin,
  type ComponentHealth,
  type ComponentHealthStatus,
  type DatabaseHealthDetails,
  type RedisHealthDetails,
  type AIRuntimeHealthDetails,
  type VASHealthDetails,
  type NLPChatHealthDetails,
} from '../../state';
import { ComponentStatusItem } from './ComponentStatusItem';
import './SystemHealthCard.css';

/**
 * Component order for consistent display
 */
const COMPONENT_ORDER = ['database', 'redis', 'ai_runtime', 'vas', 'nlp_chat'] as const;

/**
 * Extract detail string from component details
 */
function getComponentDetail(
  componentKey: string,
  component: ComponentHealth | undefined
): string | null {
  if (!component?.details) return null;

  switch (componentKey) {
    case 'database': {
      const details = component.details as DatabaseHealthDetails;
      if (details.pool_checkedout != null) {
        return `${details.pool_checkedout} connections`;
      }
      return null;
    }
    case 'redis': {
      const details = component.details as RedisHealthDetails;
      if (details.used_memory_human) {
        return details.used_memory_human;
      }
      return null;
    }
    case 'ai_runtime': {
      const details = component.details as AIRuntimeHealthDetails;
      if (details.models_loaded?.length) {
        return `${details.models_loaded.length} model${details.models_loaded.length > 1 ? 's' : ''}`;
      }
      return null;
    }
    case 'vas': {
      const details = component.details as VASHealthDetails;
      if (details.version) {
        return `v${details.version}`;
      }
      return null;
    }
    case 'nlp_chat': {
      const details = component.details as NLPChatHealthDetails;
      if (details.ollama_status) {
        return details.ollama_status === 'healthy' ? 'LLM Ready' : details.ollama_status;
      }
      return null;
    }
    default:
      return null;
  }
}

/**
 * System Health Card (F4 §4.1 Extended)
 *
 * Displays system health status for all components on the Overview page.
 *
 * Per Task Requirements:
 * - Shows health status for Database, Redis, AI Runtime, VAS
 * - Shows latency for each component
 * - Shows uptime and last check time
 * - Links to detailed health page (Admin only)
 *
 * Per F6:
 * - Health data polled every 30s via useHealthQuery
 * - Graceful handling of missing components
 * - No assumptions about data presence
 */
export function SystemHealthCard() {
  const isAdmin = useIsAdmin();
  const { data, isLoading, isError } = useHealthQuery();

  // Derive component statuses
  const componentStatuses = useMemo(() => {
    const components = data?.components;
    if (!components) {
      return COMPONENT_ORDER.map((key) => ({
        key,
        name: getComponentDisplayName(key),
        status: 'unhealthy' as ComponentHealthStatus,
        latencyMs: null,
        detail: null,
      }));
    }

    return COMPONENT_ORDER.map((key) => {
      const component = components[key];
      return {
        key,
        name: getComponentDisplayName(key),
        status: component?.status ?? 'unhealthy',
        latencyMs: component?.latency_ms,
        detail: getComponentDetail(key, component),
      };
    });
  }, [data]);

  // Calculate time since last data update (from backend timestamp)
  const lastCheckDisplay = useMemo(() => {
    const timestamp = data?.timestamp;
    if (timestamp) {
      return getTimeSinceLastCheck(timestamp);
    }
    // Fallback when no timestamp available
    return isLoading ? 'Checking...' : 'Unknown';
  }, [data, isLoading]);

  // Uptime display
  const uptimeDisplay = useMemo(() => {
    return formatUptime(data?.uptime_seconds);
  }, [data]);

  // Error state
  if (isError && !data) {
    return (
      <section className="system-health-card system-health-card--error" aria-label="System Health">
        <header className="system-health-card__header">
          <h2 className="system-health-card__title">System Health</h2>
        </header>
        <div className="system-health-card__body system-health-card__body--error">
          <span className="system-health-card__error-icon" aria-hidden="true">!</span>
          <span className="system-health-card__error-text">Unable to check system health</span>
        </div>
      </section>
    );
  }

  return (
    <section className="system-health-card" aria-label="System Health">
      <header className="system-health-card__header">
        <h2 className="system-health-card__title">System Health</h2>
        {isAdmin && (
          <Link to="/settings/health" className="system-health-card__link">
            View All &rarr;
          </Link>
        )}
      </header>

      <div className="system-health-card__body">
        <div className="system-health-card__components" role="list">
          {componentStatuses.map(({ key, name, status, latencyMs, detail }) => (
            <ComponentStatusItem
              key={key}
              name={name}
              status={status}
              latencyMs={latencyMs}
              detail={detail}
              isLoading={isLoading && !data}
            />
          ))}
        </div>

        <div className="system-health-card__footer">
          <span className="system-health-card__meta">
            Uptime: <strong>{uptimeDisplay}</strong>
          </span>
          <span className="system-health-card__meta">
            Last check: <strong>{lastCheckDisplay}</strong>
          </span>
        </div>
      </div>
    </section>
  );
}
