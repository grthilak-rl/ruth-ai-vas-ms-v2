import { useCallback, useState } from 'react';
import { useDevicesQuery, useHealthQuery, useModelsStatusQuery } from '../../state';
import { SystemHealthSkeleton, SystemHealthView } from '../../components/system-health';
import { ProductBrandingCard } from './ProductBrandingCard';

/**
 * Settings -> System. Path: /settings/system.
 *
 * Product branding (whose product this is; admin-only to change, see
 * ProductBrandingCard), then service status, component health and model
 * health. The health part is read-only and open: every endpoint behind it
 * (/health, /models/status) is unauthenticated, so it needs no admin token
 * and shows the same thing to everyone.
 *
 * The previous version of this page also rendered a "Recent Events" audit
 * feed built by generateMockAuditEvents() — three hardcoded entries
 * ("Fall Detection model updated", "System recovered from degraded
 * state") with timestamps computed from Date.now(), presented exactly like
 * real diagnostics. That has been deleted rather than reimplemented: real
 * audit data exists only for project lifecycle, and it is shown where it
 * belongs, in the Project tab.
 */
export function SettingsSystemTab() {
  const {
    data: health,
    isError: isHealthError,
    refetch: refetchHealth,
    isFetching: isHealthFetching,
  } = useHealthQuery();

  const {
    data: modelsData,
    isLoading: isModelsLoading,
    refetch: refetchModels,
  } = useModelsStatusQuery();

  // Cameras, for the monitoring-coverage signal (BL-11). Uses the shared
  // devices query, so it costs no extra request on a page that other
  // views have usually already warmed.
  const { data: devicesData, isLoading: isDevicesLoading, refetch: refetchDevices } =
    useDevicesQuery();

  const [isManualRefresh, setIsManualRefresh] = useState(false);

  const handleRefresh = useCallback(async () => {
    setIsManualRefresh(true);
    try {
      await Promise.all([refetchHealth(), refetchModels(), refetchDevices()]);
    } finally {
      setIsManualRefresh(false);
    }
  }, [refetchHealth, refetchModels, refetchDevices]);

  let healthView;
  if (isHealthError && !health) {
    healthView = (
      <div className="error-state">
        <p>Unable to load system health data.</p>
        <button onClick={() => refetchHealth()}>Retry</button>
      </div>
    );
  } else if (!health) {
    healthView = <SystemHealthSkeleton />;
  } else {
    healthView = (
      <SystemHealthView
        health={health}
        models={modelsData?.models ?? []}
        modelsLoading={isModelsLoading}
        devices={devicesData?.items ?? []}
        devicesLoading={isDevicesLoading}
        onRefresh={handleRefresh}
        isRefreshing={isManualRefresh || isHealthFetching}
      />
    );
  }

  return (
    <>
      <ProductBrandingCard />
      {healthView}
    </>
  );
}
