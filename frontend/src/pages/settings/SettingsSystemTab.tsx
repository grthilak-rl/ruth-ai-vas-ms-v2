import { useCallback, useState } from 'react';
import { useDevicesQuery, useHealthQuery, useModelsStatusQuery } from '../../state';
import { SystemHealthSkeleton, SystemHealthView } from '../../components/system-health';

/**
 * Settings -> System. Path: /settings/system.
 *
 * Service status, component health and model health. Read-only and open:
 * every endpoint behind it (/health, /models/status) is unauthenticated,
 * so this tab needs no admin token and shows the same thing to everyone.
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
    isLoading: isHealthLoading,
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

  if (isHealthLoading && !health) {
    return <SystemHealthSkeleton />;
  }

  if (isHealthError && !health) {
    return (
      <div className="error-state">
        <p>Unable to load system health data.</p>
        <button onClick={() => refetchHealth()}>Retry</button>
      </div>
    );
  }

  if (!health) {
    return <SystemHealthSkeleton />;
  }

  return (
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
