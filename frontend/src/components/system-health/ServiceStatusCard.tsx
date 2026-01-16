import { useState, useCallback } from 'react';
import type {
  ComponentHealth,
  DatabaseHealthDetails,
  RedisHealthDetails,
  AIRuntimeHealthDetails,
  VASHealthDetails,
  NLPChatHealthDetails,
} from '../../state';
import './ServiceStatusCard.css';

export type ServiceHealthStatus = 'healthy' | 'degraded' | 'offline';

/**
 * Detail item for expanded view
 */
interface DetailItem {
  label: string;
  value: string | number | null | undefined;
  unit?: string;
}

interface ServiceStatusCardProps {
  /** Service name (e.g., "Ruth Backend", "AI Runtime") */
  serviceName: string;
  /** Current health status */
  status: ServiceHealthStatus;
  /** Human-readable description of current state */
  description?: string;
  /** Last updated timestamp (displayed as relative) */
  lastUpdated?: string;
  /** Whether the card is expandable */
  expandable?: boolean;
  /** Detailed component health data for expanded view */
  components?: {
    database?: ComponentHealth;
    redis?: ComponentHealth;
    ai_runtime?: ComponentHealth;
    vas?: ComponentHealth;
    nlp_chat?: ComponentHealth;
  };
  /** Service type to determine which details to show */
  serviceType?: 'backend' | 'ai_runtime' | 'video' | 'nlp_chat';
}

/**
 * Service Status Card (F4 §9.1) - Enhanced with Expandable Details
 *
 * Shows health status for a single service with expandable detailed metrics.
 *
 * Per E8 Constraints:
 * - No pod, container, or process names
 * - Human-readable descriptions
 * - Expandable to show detailed metrics (latency, pool sizes, etc.)
 */
export function ServiceStatusCard({
  serviceName,
  status,
  description,
  lastUpdated,
  expandable = false,
  components,
  serviceType,
}: ServiceStatusCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const toggleExpanded = useCallback(() => {
    if (expandable) {
      setIsExpanded(prev => !prev);
    }
  }, [expandable]);

  const statusLabel = getStatusLabel(status);
  const statusIcon = getStatusIcon(status);

  // Get detailed items based on service type
  const detailItems = getDetailItems(serviceType, components);
  const hasDetails = expandable && detailItems.length > 0;

  return (
    <div
      className={`service-status-card service-status-card--${status} ${hasDetails ? 'service-status-card--expandable' : ''} ${isExpanded ? 'service-status-card--expanded' : ''}`}
      onClick={hasDetails ? toggleExpanded : undefined}
      onKeyDown={hasDetails ? (e) => e.key === 'Enter' && toggleExpanded() : undefined}
      role={hasDetails ? 'button' : undefined}
      tabIndex={hasDetails ? 0 : undefined}
      aria-expanded={hasDetails ? isExpanded : undefined}
    >
      <div className="service-status-card__header">
        <h3 className="service-status-card__name">{serviceName}</h3>
        {hasDetails && (
          <span className={`service-status-card__chevron ${isExpanded ? 'service-status-card__chevron--expanded' : ''}`}>
            ▼
          </span>
        )}
      </div>
      <div className="service-status-card__content">
        <span className={`service-status-card__indicator service-status-card__indicator--${status}`}>
          <span className="service-status-card__icon">{statusIcon}</span>
          <span className="service-status-card__label">{statusLabel}</span>
        </span>
        {description && (
          <p className="service-status-card__description">{description}</p>
        )}
      </div>

      {/* Expanded Details Section */}
      {hasDetails && isExpanded && (
        <div className="service-status-card__details">
          {detailItems.map((item, index) => (
            <div key={index} className="service-status-card__detail-item">
              <span className="service-status-card__detail-label">{item.label}</span>
              <span className="service-status-card__detail-value">
                {formatDetailValue(item.value, item.unit)}
              </span>
            </div>
          ))}
        </div>
      )}

      {lastUpdated && (
        <div className="service-status-card__footer">
          <span className="service-status-card__updated">
            Updated {formatRelativeTime(lastUpdated)}
          </span>
        </div>
      )}
    </div>
  );
}

/**
 * Get detail items based on service type and component data
 */
function getDetailItems(
  serviceType: ServiceStatusCardProps['serviceType'],
  components: ServiceStatusCardProps['components']
): DetailItem[] {
  if (!components) return [];

  const items: DetailItem[] = [];

  switch (serviceType) {
    case 'backend': {
      // Database details
      const db = components.database;
      if (db) {
        items.push({
          label: 'Database Status',
          value: capitalizeStatus(db.status),
        });
        items.push({
          label: 'Database Latency',
          value: db.latency_ms,
          unit: 'ms',
        });

        const dbDetails = db.details as DatabaseHealthDetails | undefined;
        if (dbDetails) {
          if (dbDetails.pool_size != null) {
            items.push({
              label: 'Pool Size',
              value: dbDetails.pool_size,
            });
          }
          if (dbDetails.pool_checkedout != null) {
            items.push({
              label: 'Active Connections',
              value: dbDetails.pool_checkedout,
            });
          }
          if (dbDetails.pool_checkedin != null) {
            items.push({
              label: 'Idle Connections',
              value: dbDetails.pool_checkedin,
            });
          }
        }
      }

      // Redis details
      const redis = components.redis;
      if (redis) {
        items.push({
          label: 'Redis Status',
          value: capitalizeStatus(redis.status),
        });
        items.push({
          label: 'Redis Latency',
          value: redis.latency_ms,
          unit: 'ms',
        });

        const redisDetails = redis.details as RedisHealthDetails | undefined;
        if (redisDetails) {
          if (redisDetails.used_memory_human) {
            items.push({
              label: 'Used Memory',
              value: redisDetails.used_memory_human,
            });
          }
          if (redisDetails.connected_clients != null) {
            items.push({
              label: 'Connected Clients',
              value: redisDetails.connected_clients,
            });
          }
        }
      }
      break;
    }

    case 'ai_runtime': {
      const aiRuntime = components.ai_runtime;
      if (aiRuntime) {
        items.push({
          label: 'Status',
          value: capitalizeStatus(aiRuntime.status),
        });
        items.push({
          label: 'Latency',
          value: aiRuntime.latency_ms,
          unit: 'ms',
        });

        const aiDetails = aiRuntime.details as AIRuntimeHealthDetails | undefined;
        if (aiDetails) {
          if (aiDetails.models_loaded?.length) {
            items.push({
              label: 'Models Loaded',
              value: aiDetails.models_loaded.join(', '),
            });
          }
          if (aiDetails.gpu_available != null) {
            items.push({
              label: 'GPU Available',
              value: aiDetails.gpu_available ? 'Yes' : 'No',
            });
          }
          if (aiDetails.hardware_type) {
            items.push({
              label: 'Hardware Type',
              value: aiDetails.hardware_type.toUpperCase(),
            });
          }
        }

        if (aiRuntime.error) {
          items.push({
            label: 'Error',
            value: aiRuntime.error,
          });
        }
      }
      break;
    }

    case 'video': {
      const vas = components.vas;
      if (vas) {
        items.push({
          label: 'Status',
          value: capitalizeStatus(vas.status),
        });
        items.push({
          label: 'Latency',
          value: vas.latency_ms,
          unit: 'ms',
        });

        const vasDetails = vas.details as VASHealthDetails | undefined;
        if (vasDetails) {
          if (vasDetails.version) {
            items.push({
              label: 'Version',
              value: vasDetails.version,
            });
          }
          if (vasDetails.service) {
            items.push({
              label: 'Service',
              value: vasDetails.service,
            });
          }
        }

        if (vas.error) {
          items.push({
            label: 'Error',
            value: vas.error,
          });
        }
      }
      break;
    }

    case 'nlp_chat': {
      const nlpChat = components.nlp_chat;
      if (nlpChat) {
        items.push({
          label: 'Status',
          value: capitalizeStatus(nlpChat.status),
        });
        items.push({
          label: 'Latency',
          value: nlpChat.latency_ms,
          unit: 'ms',
        });

        const nlpDetails = nlpChat.details as NLPChatHealthDetails | undefined;
        if (nlpDetails) {
          if (nlpDetails.ollama_status) {
            items.push({
              label: 'LLM Status',
              value: capitalizeStatus(nlpDetails.ollama_status),
            });
          }
          if (nlpDetails.version) {
            items.push({
              label: 'Version',
              value: nlpDetails.version,
            });
          }
          if (nlpDetails.service) {
            items.push({
              label: 'Service',
              value: nlpDetails.service,
            });
          }
          if (nlpDetails.models_available?.length) {
            items.push({
              label: 'Available Models',
              value: nlpDetails.models_available.join(', '),
            });
          }
        }

        if (nlpChat.error) {
          items.push({
            label: 'Error',
            value: nlpChat.error,
          });
        }
      }
      break;
    }
  }

  return items;
}

function capitalizeStatus(status: string | undefined): string {
  if (!status) return 'Unknown';
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function formatDetailValue(
  value: string | number | null | undefined,
  unit?: string
): string {
  if (value == null) return 'N/A';
  if (unit) return `${value}${unit}`;
  return String(value);
}

function getStatusLabel(status: ServiceHealthStatus): string {
  switch (status) {
    case 'healthy':
      return 'Healthy';
    case 'degraded':
      return 'Degraded';
    case 'offline':
      return 'Offline';
  }
}

function getStatusIcon(status: ServiceHealthStatus): string {
  switch (status) {
    case 'healthy':
      return '●';
    case 'degraded':
      return '◐';
    case 'offline':
      return '○';
  }
}

function formatRelativeTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSecs = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffSecs / 60);
    const diffHours = Math.floor(diffMins / 60);

    if (diffSecs < 60) {
      return `${diffSecs}s ago`;
    } else if (diffMins < 60) {
      return `${diffMins}m ago`;
    } else if (diffHours < 24) {
      return `${diffHours}h ago`;
    }
    return date.toLocaleDateString();
  } catch {
    return 'recently';
  }
}
