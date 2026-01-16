import { Navigate } from 'react-router-dom';
import {
  useModelsStatusQuery,
  useIsAdmin,
  getOverallModelHealth,
} from '../../state';
import { ModelStatusCard } from '../../components/system-health';
import './ModelStatusPage.css';

/**
 * Model Status Page (F2 Path: /settings/models)
 *
 * Admin-only view for AI model versions and health.
 *
 * Per F4 §8:
 * - List all registered models
 * - Show version, status, health for each
 * - Expandable detail view
 *
 * Per E8 Constraints:
 * - Only visible to Admin role
 * - No inference internals exposed
 * - Version numbers visible only here
 */
export function ModelStatusPage() {
  const isAdmin = useIsAdmin();

  // If not admin, redirect to overview
  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  return <ModelStatusContent />;
}

function ModelStatusContent() {
  const {
    data: modelsData,
    isLoading,
    isError,
    refetch,
  } = useModelsStatusQuery();

  // Overall health summary
  const overallHealth = modelsData?.models
    ? getOverallModelHealth(modelsData.models)
    : 'unavailable';

  // Loading state
  if (isLoading) {
    return (
      <div className="model-status-page">
        <div className="model-status-page__header">
          <h1 className="model-status-page__title">AI Models</h1>
          <span className="model-status-page__badge">Admin Only</span>
        </div>
        <div className="model-status-page__loading">
          Loading model status...
        </div>
      </div>
    );
  }

  // Error state
  if (isError) {
    return (
      <div className="model-status-page">
        <div className="model-status-page__header">
          <h1 className="model-status-page__title">AI Models</h1>
          <span className="model-status-page__badge">Admin Only</span>
        </div>
        <div className="model-status-page__error">
          <p>Unable to load model status.</p>
          <p className="model-status-page__error-hint">
            Could not connect to AI Runtime.
          </p>
          <button
            className="model-status-page__retry-btn"
            onClick={() => refetch()}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const models = modelsData?.models ?? [];

  // Empty state
  if (models.length === 0) {
    return (
      <div className="model-status-page">
        <div className="model-status-page__header">
          <h1 className="model-status-page__title">AI Models</h1>
          <span className="model-status-page__badge">Admin Only</span>
        </div>
        <div className="model-status-page__empty">
          <p>No AI models deployed</p>
          <p className="model-status-page__empty-hint">
            Models are deployed via the AI Runtime system.
            Contact the platform team to add models.
          </p>
        </div>
      </div>
    );
  }

  // Count models by health
  const healthCounts = {
    healthy: models.filter(m => m.health === 'healthy').length,
    degraded: models.filter(m => m.health === 'degraded').length,
    unhealthy: models.filter(m => m.health === 'unhealthy').length,
  };

  const hasIssues = healthCounts.degraded > 0 || healthCounts.unhealthy > 0;

  return (
    <div className="model-status-page">
      <div className="model-status-page__header">
        <h1 className="model-status-page__title">AI Models</h1>
        <span className="model-status-page__badge">Admin Only</span>
      </div>

      {/* Summary */}
      <div className="model-status-page__summary">
        <span className={`model-status-page__health model-status-page__health--${overallHealth}`}>
          {healthCounts.healthy}/{models.length} models healthy
        </span>
        {hasIssues && (
          <span className="model-status-page__issues">
            {healthCounts.degraded > 0 && `${healthCounts.degraded} degraded`}
            {healthCounts.degraded > 0 && healthCounts.unhealthy > 0 && ', '}
            {healthCounts.unhealthy > 0 && `${healthCounts.unhealthy} unhealthy`}
          </span>
        )}
      </div>

      {/* Warning banner if issues */}
      {hasIssues && (
        <div className="model-status-page__warning">
          <p>
            {healthCounts.unhealthy > 0
              ? 'Some models require attention. Detection may be unavailable.'
              : 'Some models are experiencing issues. Detection may be delayed.'}
          </p>
        </div>
      )}

      {/* Model list */}
      <div className="model-status-page__list">
        {models.map(model => (
          <ModelStatusCard
            key={model.model_id}
            model={model}
            isAdmin={true}
            expandable={true}
          />
        ))}
      </div>
    </div>
  );
}
