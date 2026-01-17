import { useMemo } from 'react';
import {
  useHardwareQuery,
  getUsageLevel,
  formatGB,
  formatPercent,
  getTimeSinceUpdate,
  type UsageLevel,
  type GPUMetrics,
  type CPUMetrics,
  type RAMMetrics,
  type ModelsMetrics,
  type CapacityMetrics,
} from '../../state';
import './HardwareCapacityCard.css';

/**
 * Hardware Capacity Card
 *
 * Displays real-time hardware utilization metrics for the Ruth AI dashboard.
 * Includes GPU, CPU, RAM, loaded AI models, and capacity estimates.
 *
 * Features:
 * - Auto-refresh every 5 seconds
 * - Color-coded usage bars (green/yellow/red)
 * - Graceful handling when GPU unavailable
 * - Never fails - always shows partial data
 */
export function HardwareCapacityCard() {
  const { data, isLoading, isError, dataUpdatedAt } = useHardwareQuery();

  // Calculate time since last update
  const lastUpdateDisplay = useMemo(() => {
    if (!data?.timestamp) return 'Unknown';
    return getTimeSinceUpdate(data.timestamp);
  }, [data?.timestamp]);

  // Determine if data is stale (>10 seconds old)
  const isStale = useMemo(() => {
    if (!dataUpdatedAt) return false;
    const now = Date.now();
    return now - dataUpdatedAt > 10000;
  }, [dataUpdatedAt]);

  // Error state - show error card
  if (isError && !data) {
    return (
      <section className="hardware-capacity-card hardware-capacity-card--error" aria-label="Hardware Capacity">
        <header className="hardware-capacity-card__header">
          <h2 className="hardware-capacity-card__title">Hardware Capacity</h2>
        </header>
        <div className="hardware-capacity-card__body hardware-capacity-card__body--error">
          <span className="hardware-capacity-card__error-icon" aria-hidden="true">!</span>
          <span className="hardware-capacity-card__error-text">Unable to load hardware metrics</span>
        </div>
      </section>
    );
  }

  return (
    <section
      className={`hardware-capacity-card ${isLoading && !data ? 'hardware-capacity-card--loading' : ''} ${isStale ? 'hardware-capacity-card--stale' : ''}`}
      aria-label="Hardware Capacity"
    >
      <header className="hardware-capacity-card__header">
        <h2 className="hardware-capacity-card__title">Hardware Capacity</h2>
        <span className="hardware-capacity-card__refresh">
          {isLoading ? '⟳' : ''} {lastUpdateDisplay}
        </span>
      </header>

      <div className="hardware-capacity-card__body">
        {/* GPU Section */}
        <GPUSection gpu={data?.gpu} isLoading={isLoading && !data} />

        {/* CPU Section */}
        <CPUSection cpu={data?.cpu} isLoading={isLoading && !data} />

        {/* RAM Section */}
        <RAMSection ram={data?.ram} isLoading={isLoading && !data} />

        {/* Divider */}
        <div className="hardware-capacity-card__divider" />

        {/* Capacity Summary */}
        <CapacitySummary
          models={data?.models}
          capacity={data?.capacity}
          isLoading={isLoading && !data}
        />
      </div>
    </section>
  );
}

// ============================================================================
// Sub-components
// ============================================================================

interface GPUSectionProps {
  gpu?: GPUMetrics;
  isLoading: boolean;
}

function GPUSection({ gpu, isLoading }: GPUSectionProps) {
  const usageLevel = getUsageLevel(gpu?.vram_percent);

  if (isLoading) {
    return (
      <div className="hardware-capacity-card__section hardware-capacity-card__section--loading">
        <div className="hardware-capacity-card__section-header">
          <span className="hardware-capacity-card__section-label">GPU</span>
          <span className="hardware-capacity-card__section-value">...</span>
        </div>
        <div className="hardware-capacity-card__progress-bar">
          <div className="hardware-capacity-card__progress-fill hardware-capacity-card__progress-fill--loading" style={{ width: '50%' }} />
        </div>
      </div>
    );
  }

  if (!gpu?.available) {
    return (
      <div className="hardware-capacity-card__section hardware-capacity-card__section--disabled">
        <div className="hardware-capacity-card__section-header">
          <span className="hardware-capacity-card__section-label">GPU</span>
          <span className="hardware-capacity-card__cpu-mode-badge">CPU Mode</span>
        </div>
        <span className="hardware-capacity-card__section-detail">No GPU detected</span>
      </div>
    );
  }

  return (
    <div className="hardware-capacity-card__section">
      <div className="hardware-capacity-card__section-header">
        <span className="hardware-capacity-card__section-label">GPU: {gpu.name ?? 'Unknown'}</span>
        <span className={`hardware-capacity-card__section-value hardware-capacity-card__section-value--${usageLevel}`}>
          {formatPercent(gpu.vram_percent)} VRAM
        </span>
      </div>
      <UsageBar percent={gpu.vram_percent ?? 0} level={usageLevel} />
      <div className="hardware-capacity-card__section-details">
        <span>{formatGB(gpu.vram_used_gb)} / {formatGB(gpu.vram_total_gb)}</span>
        {gpu.utilization_percent != null && (
          <span className="hardware-capacity-card__gpu-util">
            {formatPercent(gpu.utilization_percent)} compute
          </span>
        )}
        {gpu.temperature_c != null && (
          <span className="hardware-capacity-card__gpu-temp">{gpu.temperature_c}°C</span>
        )}
      </div>
    </div>
  );
}

interface CPUSectionProps {
  cpu?: CPUMetrics;
  isLoading: boolean;
}

function CPUSection({ cpu, isLoading }: CPUSectionProps) {
  const usageLevel = getUsageLevel(cpu?.usage_percent);

  if (isLoading) {
    return (
      <div className="hardware-capacity-card__section hardware-capacity-card__section--loading">
        <div className="hardware-capacity-card__section-header">
          <span className="hardware-capacity-card__section-label">CPU</span>
          <span className="hardware-capacity-card__section-value">...</span>
        </div>
        <div className="hardware-capacity-card__progress-bar">
          <div className="hardware-capacity-card__progress-fill hardware-capacity-card__progress-fill--loading" style={{ width: '30%' }} />
        </div>
      </div>
    );
  }

  const coresDisplay = cpu?.cores ? `${cpu.cores} cores` : '';
  const modelDisplay = cpu?.model ? cpu.model.split(' ').slice(0, 3).join(' ') : 'Unknown';

  return (
    <div className="hardware-capacity-card__section">
      <div className="hardware-capacity-card__section-header">
        <span className="hardware-capacity-card__section-label">CPU: {coresDisplay}</span>
        <span className={`hardware-capacity-card__section-value hardware-capacity-card__section-value--${usageLevel}`}>
          {formatPercent(cpu?.usage_percent)}
        </span>
      </div>
      <UsageBar percent={cpu?.usage_percent ?? 0} level={usageLevel} />
      <div className="hardware-capacity-card__section-details">
        <span className="hardware-capacity-card__cpu-model">{modelDisplay}</span>
      </div>
    </div>
  );
}

interface RAMSectionProps {
  ram?: RAMMetrics;
  isLoading: boolean;
}

function RAMSection({ ram, isLoading }: RAMSectionProps) {
  const usageLevel = getUsageLevel(ram?.percent);

  if (isLoading) {
    return (
      <div className="hardware-capacity-card__section hardware-capacity-card__section--loading">
        <div className="hardware-capacity-card__section-header">
          <span className="hardware-capacity-card__section-label">RAM</span>
          <span className="hardware-capacity-card__section-value">...</span>
        </div>
        <div className="hardware-capacity-card__progress-bar">
          <div className="hardware-capacity-card__progress-fill hardware-capacity-card__progress-fill--loading" style={{ width: '40%' }} />
        </div>
      </div>
    );
  }

  return (
    <div className="hardware-capacity-card__section">
      <div className="hardware-capacity-card__section-header">
        <span className="hardware-capacity-card__section-label">RAM: {formatGB(ram?.total_gb)}</span>
        <span className={`hardware-capacity-card__section-value hardware-capacity-card__section-value--${usageLevel}`}>
          {formatPercent(ram?.percent)}
        </span>
      </div>
      <UsageBar percent={ram?.percent ?? 0} level={usageLevel} />
      <div className="hardware-capacity-card__section-details">
        <span>{formatGB(ram?.used_gb)} used</span>
      </div>
    </div>
  );
}

interface CapacitySummaryProps {
  models?: ModelsMetrics;
  capacity?: CapacityMetrics;
  isLoading: boolean;
}

function CapacitySummary({ models, capacity, isLoading }: CapacitySummaryProps) {
  if (isLoading) {
    return (
      <div className="hardware-capacity-card__summary hardware-capacity-card__summary--loading">
        <div className="hardware-capacity-card__summary-item">
          <span className="hardware-capacity-card__summary-label">Models Loaded</span>
          <span className="hardware-capacity-card__summary-value">—</span>
        </div>
        <div className="hardware-capacity-card__summary-item">
          <span className="hardware-capacity-card__summary-label">Camera Capacity</span>
          <span className="hardware-capacity-card__summary-value">—</span>
        </div>
      </div>
    );
  }

  // Determine headroom status
  const headroomLevel: UsageLevel =
    (capacity?.headroom_percent ?? 0) >= 50 ? 'healthy' :
    (capacity?.headroom_percent ?? 0) >= 20 ? 'warning' : 'critical';

  // Count healthy services
  const healthyServices = models?.services.filter(s => s.status === 'healthy').length ?? 0;
  const totalServices = models?.services.length ?? 0;

  return (
    <div className="hardware-capacity-card__summary">
      <div className="hardware-capacity-card__summary-item">
        <span className="hardware-capacity-card__summary-label">Models Loaded</span>
        <span className="hardware-capacity-card__summary-value">
          {models?.loaded_count ?? 0}
          <span className="hardware-capacity-card__summary-detail">
            ({healthyServices}/{totalServices} services)
          </span>
        </span>
      </div>
      <div className="hardware-capacity-card__summary-item">
        <span className="hardware-capacity-card__summary-label">Camera Capacity</span>
        <span className={`hardware-capacity-card__summary-value hardware-capacity-card__summary-value--${headroomLevel}`}>
          {capacity?.current_cameras ?? 0} / {capacity?.estimated_max_cameras ?? 0}
          <span className="hardware-capacity-card__summary-detail">
            ({capacity?.headroom_percent ?? 0}% headroom)
          </span>
        </span>
      </div>
    </div>
  );
}

interface UsageBarProps {
  percent: number;
  level: UsageLevel;
}

function UsageBar({ percent, level }: UsageBarProps) {
  const clampedPercent = Math.min(100, Math.max(0, percent));

  return (
    <div className="hardware-capacity-card__progress-bar">
      <div
        className={`hardware-capacity-card__progress-fill hardware-capacity-card__progress-fill--${level}`}
        style={{ width: `${clampedPercent}%` }}
        role="progressbar"
        aria-valuenow={clampedPercent}
        aria-valuemin={0}
        aria-valuemax={100}
      />
    </div>
  );
}
