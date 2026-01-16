import { useMemo } from 'react';
import {
  useViolationsQuery,
  useDevicesQuery,
  useModelsStatusQuery,
} from '../../state';
import { SummaryCard } from './SummaryCard';
import './SummaryCards.css';

/**
 * Summary Cards Section (F4 §4.1)
 *
 * Displays three summary cards:
 * - Open Alerts count
 * - Cameras Live (active / total)
 * - Models Active (healthy / total)
 *
 * Per F6 §6.2:
 * - NO arithmetic across different API calls
 * - Values displayed exactly as received from each query
 * - Each card loads independently
 *
 * Per F4 States:
 * - Each card shows its own loading/error state
 * - Partial failures do not block other cards
 */
export function SummaryCards() {
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

  return (
    <div className="summary-cards">
      <SummaryCard
        title="Open Alerts"
        value={openViolationsCount}
        isLoading={isViolationsLoading}
        isError={isViolationsError}
        linkTo="/alerts"
        linkLabel="View All"
      />

      <SummaryCard
        title="Cameras Live"
        value={cameraCounts.live}
        secondaryValue={cameraCounts.total}
        variant="ratio"
        isLoading={isDevicesLoading}
        isError={isDevicesError}
        linkTo="/cameras"
        linkLabel="View All"
      />

      <SummaryCard
        title="Models Active"
        value={modelCounts.healthy}
        secondaryValue={modelCounts.total}
        variant="ratio"
        isLoading={isModelsLoading}
        isError={isModelsError}
        /* No link for Operator/Supervisor - Models page is Admin-only */
      />
    </div>
  );
}
