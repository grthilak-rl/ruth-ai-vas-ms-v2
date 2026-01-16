import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  useViolationsQuery,
  useDevicesQuery,
  useModelsStatusQuery,
  useHealthQuery,
  formatUptime,
  getComponentDisplayName,
  useIsAdmin,
  type ComponentHealthStatus,
} from '../../state';
import './TopStatusBar.css';

/**
 * Component order for health indicators
 */
const COMPONENT_ORDER = ['database', 'redis', 'ai_runtime', 'vas', 'nlp_chat'] as const;

/**
 * Top Status Bar (Enhanced Overview Header)
 *
 * Displays detailed summary cards and system health in a prominent header section.
 * Each metric card shows the value prominently with a descriptive label and optional link.
 * System health shows all components with their status and latency.
 */
export function TopStatusBar() {
  // Fetch violations for open count
  const {
    data: violationsData,
    isLoading: isViolationsLoading,
    isError: isViolationsError,
  } = useViolationsQuery({ status: 'open' });

  // Fetch devices for camera count
  const {
    data: devicesData,
    isLoading: isDevicesLoading,
    isError: isDevicesError,
  } = useDevicesQuery();

  // Fetch models for model health
  const {
    data: modelsData,
    isLoading: isModelsLoading,
    isError: isModelsError,
  } = useModelsStatusQuery();

  // Fetch system health
  const {
    data: healthData,
    isLoading: isHealthLoading,
    isError: isHealthError,
  } = useHealthQuery();

  const isAdmin = useIsAdmin();

  // Derive open violations count
  const openViolationsCount = useMemo(() => {
    if (!violationsData?.items) return null;
    return violationsData.total;
  }, [violationsData]);

  // Derive camera counts
  const cameraCounts = useMemo(() => {
    if (!devicesData?.items) return { live: null, total: null };
    const total = devicesData.items.length;
    const live = devicesData.items.filter(
      (d) => d.is_active && d.streaming.active
    ).length;
    return { live, total };
  }, [devicesData]);

  // Derive model counts
  const modelCounts = useMemo(() => {
    if (!modelsData?.models) return { healthy: null, total: null };
    const total = modelsData.models.length;
    const healthy = modelsData.models.filter(
      (m) => m.health === 'healthy' && m.status === 'active'
    ).length;
    return { healthy, total };
  }, [modelsData]);

  // Derive health statuses with latency
  const healthStatuses = useMemo(() => {
    const components = healthData?.components;
    return COMPONENT_ORDER.map((key) => ({
      key,
      name: getComponentDisplayName(key),
      status: (components?.[key]?.status ?? 'unhealthy') as ComponentHealthStatus,
      latencyMs: components?.[key]?.latency_ms,
    }));
  }, [healthData]);

  // Overall health status
  const overallHealth = useMemo(() => {
    const statuses = healthStatuses.map((h) => h.status);
    if (statuses.every((s) => s === 'healthy')) return 'healthy';
    if (statuses.some((s) => s === 'unhealthy')) return 'unhealthy';
    return 'degraded';
  }, [healthStatuses]);

  // Uptime display
  const uptimeDisplay = useMemo(() => {
    return formatUptime(healthData?.uptime_seconds);
  }, [healthData]);

  return (
    <div className="top-status-bar">
      {/* Summary Metric Cards */}
      <div className="top-status-bar__cards">
        <MetricCard
          label="Open Alerts"
          value={openViolationsCount}
          isLoading={isViolationsLoading}
          isError={isViolationsError}
          linkTo="/alerts"
          linkLabel="View All"
          variant="alert"
          icon="!"
        />
        <MetricCard
          label="Cameras Live"
          value={cameraCounts.live}
          secondaryValue={cameraCounts.total}
          isLoading={isDevicesLoading}
          isError={isDevicesError}
          linkTo="/cameras"
          linkLabel="View All"
          icon="◉"
        />
        <MetricCard
          label="Models Active"
          value={modelCounts.healthy}
          secondaryValue={modelCounts.total}
          isLoading={isModelsLoading}
          isError={isModelsError}
          icon="◆"
        />
      </div>

      {/* System Health Panel */}
      <div className={`top-status-bar__health top-status-bar__health--${overallHealth}`}>
        <div className="top-status-bar__health-header">
          <span className="top-status-bar__health-title">System Health</span>
          <span className={`top-status-bar__health-badge top-status-bar__health-badge--${overallHealth}`}>
            {overallHealth === 'healthy' ? 'All Systems OK' : overallHealth === 'degraded' ? 'Degraded' : 'Issues'}
          </span>
        </div>
        <div className="top-status-bar__health-grid">
          {healthStatuses.map(({ key, name, status, latencyMs }) => (
            <HealthItem
              key={key}
              name={name}
              status={status}
              latencyMs={latencyMs}
              isLoading={isHealthLoading && !healthData}
            />
          ))}
        </div>
        <div className="top-status-bar__health-footer">
          <span className="top-status-bar__health-uptime">
            Uptime: <strong>{uptimeDisplay}</strong>
          </span>
          {isAdmin && (
            <Link to="/settings/health" className="top-status-bar__health-link">
              Details &rarr;
            </Link>
          )}
        </div>
        {isHealthError && !healthData && (
          <div className="top-status-bar__health-error">
            Unable to check system health
          </div>
        )}
      </div>
    </div>
  );
}

interface MetricCardProps {
  label: string;
  value: number | null;
  secondaryValue?: number | null;
  isLoading: boolean;
  isError: boolean;
  linkTo?: string;
  linkLabel?: string;
  variant?: 'default' | 'alert';
  icon?: string;
}

/**
 * Individual metric card with prominent value display
 */
function MetricCard({
  label,
  value,
  secondaryValue,
  isLoading,
  isError,
  linkTo,
  linkLabel,
  variant = 'default',
  icon,
}: MetricCardProps) {
  const displayValue = useMemo(() => {
    if (isLoading) return '—';
    if (isError || value === null) return '?';
    if (secondaryValue !== undefined && secondaryValue !== null) {
      return `${value} / ${secondaryValue}`;
    }
    return String(value);
  }, [value, secondaryValue, isLoading, isError]);

  const hasAlert = variant === 'alert' && value !== null && value > 0;

  return (
    <div
      className={`top-status-bar__card ${
        hasAlert ? 'top-status-bar__card--alert' : ''
      } ${isLoading ? 'top-status-bar__card--loading' : ''} ${
        isError ? 'top-status-bar__card--error' : ''
      }`}
    >
      {icon && (
        <span className={`top-status-bar__card-icon ${hasAlert ? 'top-status-bar__card-icon--alert' : ''}`}>
          {icon}
        </span>
      )}
      <span className={`top-status-bar__card-value ${hasAlert ? 'top-status-bar__card-value--alert' : ''}`}>
        {displayValue}
      </span>
      <span className="top-status-bar__card-label">{label}</span>
      {linkTo && linkLabel && (
        <Link to={linkTo} className="top-status-bar__card-link">
          {linkLabel} &rarr;
        </Link>
      )}
    </div>
  );
}

interface HealthItemProps {
  name: string;
  status: ComponentHealthStatus;
  latencyMs?: number | null;
  isLoading: boolean;
}

/**
 * Individual health component item with status and latency
 */
function HealthItem({ name, status, latencyMs, isLoading }: HealthItemProps) {
  const statusClass = isLoading
    ? 'top-status-bar__health-item--loading'
    : `top-status-bar__health-item--${status}`;

  const latencyDisplay = useMemo(() => {
    if (isLoading) return '...';
    if (latencyMs === null || latencyMs === undefined) return '';
    return `${latencyMs}ms`;
  }, [latencyMs, isLoading]);

  return (
    <div className={`top-status-bar__health-item ${statusClass}`}>
      <span className="top-status-bar__health-dot">●</span>
      <span className="top-status-bar__health-name">{name}</span>
      {latencyDisplay && (
        <span className="top-status-bar__health-latency">{latencyDisplay}</span>
      )}
    </div>
  );
}
