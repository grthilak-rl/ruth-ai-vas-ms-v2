import { useState } from 'react';
import type { ModelStatusInfo, ModelHealth, ModelStatus } from '../../state';
import { humanizeModelId, getModelDisplay } from '../../state';
import './ModelStatusCard.css';

interface ModelStatusCardProps {
  model: ModelStatusInfo;
  isAdmin: boolean;
  /** Optional: show expanded details */
  expandable?: boolean;
}

/**
 * Model Status Card (F4 §8.1)
 *
 * Shows health and status for a single AI model.
 *
 * Per E8:
 * - Admin sees: model name, version, status, health, cameras
 * - Operator sees: nothing (this component is Admin-only)
 *
 * Per F3 Constraints:
 * - No inference internals or metrics to operators
 * - Admins see abstracted diagnostic info
 */
export function ModelStatusCard({
  model,
  isAdmin,
  expandable = true,
}: ModelStatusCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const displayInfo = getModelDisplay(model);
  const modelName = humanizeModelId(model.model_id, isAdmin);
  const healthClass = getHealthClass(model.health);
  const statusIcon = getStatusIcon(model.status, model.health);

  return (
    <div className={`model-status-card model-status-card--${healthClass}`}>
      <div
        className="model-status-card__header"
        onClick={() => expandable && setIsExpanded(!isExpanded)}
        role={expandable ? 'button' : undefined}
        tabIndex={expandable ? 0 : undefined}
        onKeyDown={(e) => {
          if (expandable && (e.key === 'Enter' || e.key === ' ')) {
            setIsExpanded(!isExpanded);
          }
        }}
      >
        <div className="model-status-card__info">
          <h3 className="model-status-card__name">{modelName}</h3>
          {isAdmin && model.version && (
            <span className="model-status-card__version">v{model.version}</span>
          )}
        </div>
        <div className="model-status-card__status">
          <span className={`model-status-card__indicator model-status-card__indicator--${healthClass}`}>
            {statusIcon} {isAdmin ? displayInfo.adminDisplay : displayInfo.operatorDisplay}
          </span>
        </div>
        {expandable && (
          <span className="model-status-card__expand" aria-hidden="true">
            {isExpanded ? '▼' : '▶'}
          </span>
        )}
      </div>

      {isExpanded && isAdmin && (
        <div className="model-status-card__details">
          <dl className="model-status-card__details-list">
            <div className="model-status-card__detail-item">
              <dt>Status</dt>
              <dd>{formatStatus(model.status)}</dd>
            </div>
            <div className="model-status-card__detail-item">
              <dt>Health</dt>
              <dd className={`model-status-card__health-value model-status-card__health-value--${healthClass}`}>
                {formatHealth(model.health)}
              </dd>
            </div>
            <div className="model-status-card__detail-item">
              <dt>Active Cameras</dt>
              <dd>{model.cameras_active}</dd>
            </div>
            {model.last_inference_at && (
              <div className="model-status-card__detail-item">
                <dt>Last Activity</dt>
                <dd>{formatLastActivity(model.last_inference_at)}</dd>
              </div>
            )}
            {model.started_at && (
              <div className="model-status-card__detail-item">
                <dt>Started</dt>
                <dd>{formatDateTime(model.started_at)}</dd>
              </div>
            )}
          </dl>

          {/* Health issue explanation for degraded/unhealthy models */}
          {model.health !== 'healthy' && (
            <div className="model-status-card__issue">
              <p className="model-status-card__issue-message">
                {getHealthMessage(model.health, model.status)}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function getHealthClass(health: ModelHealth): string {
  switch (health) {
    case 'healthy':
      return 'healthy';
    case 'degraded':
      return 'degraded';
    case 'unhealthy':
      return 'unhealthy';
  }
}

function getStatusIcon(status: ModelStatus, health: ModelHealth): string {
  if (health === 'unhealthy' || status === 'error') return '○';
  if (health === 'degraded') return '◐';
  if (status === 'active' && health === 'healthy') return '●';
  if (status === 'starting' || status === 'stopping') return '◌';
  return '○';
}

function formatStatus(status: ModelStatus): string {
  switch (status) {
    case 'active':
      return 'Active';
    case 'idle':
      return 'Idle';
    case 'starting':
      return 'Starting';
    case 'stopping':
      return 'Stopping';
    case 'error':
      return 'Error';
  }
}

function formatHealth(health: ModelHealth): string {
  switch (health) {
    case 'healthy':
      return 'Healthy';
    case 'degraded':
      return 'Degraded';
    case 'unhealthy':
      return 'Unhealthy';
  }
}

function getHealthMessage(health: ModelHealth, status: ModelStatus): string {
  if (status === 'error') {
    return 'Model encountered an error. Detection is paused until the issue is resolved.';
  }
  if (health === 'degraded') {
    return 'Model is experiencing higher than normal latency. Detection may be delayed.';
  }
  if (health === 'unhealthy') {
    return 'Model is not responding correctly. Detection is unavailable.';
  }
  return '';
}

function formatLastActivity(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSecs = Math.floor(diffMs / 1000);

    if (diffSecs < 60) return 'Just now';
    if (diffSecs < 3600) return `${Math.floor(diffSecs / 60)}m ago`;
    if (diffSecs < 86400) return `${Math.floor(diffSecs / 3600)}h ago`;
    return formatDateTime(timestamp);
  } catch {
    return 'Unknown';
  }
}

function formatDateTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return 'Unknown';
  }
}
