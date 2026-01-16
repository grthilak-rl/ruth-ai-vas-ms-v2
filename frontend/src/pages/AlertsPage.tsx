import { useState, useCallback, useMemo } from 'react';
import { AlertsList, AlertsFilterSidebar, DEFAULT_FILTERS, type AlertFilters } from '../components/alerts';
import { useDevicesQuery } from '../state';
import './AlertsPage.css';

/**
 * Alerts List Page (F2/E5)
 *
 * Path: /alerts
 *
 * The most critical operator workflow: viewing, triaging, and
 * acting on live violations.
 *
 * Per F2 Information Architecture:
 * - Active violations requiring attention
 * - Status: open, reviewed (not dismissed/resolved)
 *
 * Layout:
 * - Left sidebar: Filter controls (Status, Date Range, Camera)
 * - Main area: Violations list
 */
export function AlertsPage() {
  // Filter state
  const [filters, setFilters] = useState<AlertFilters>(DEFAULT_FILTERS);

  // Fetch devices for camera filter dropdown
  const { data: devicesData, isLoading: devicesLoading } = useDevicesQuery();

  // Memoize cameras list
  const cameras = useMemo(() => devicesData?.items ?? [], [devicesData?.items]);

  // Handle filter changes
  const handleFiltersChange = useCallback((newFilters: AlertFilters) => {
    setFilters(newFilters);
  }, []);

  return (
    <div className="alerts-page">
      <AlertsFilterSidebar
        filters={filters}
        onFiltersChange={handleFiltersChange}
        cameras={cameras}
        camerasLoading={devicesLoading}
      />
      <main className="alerts-page__main">
        <section className="alerts-page__content">
          <AlertsList filters={filters} />
        </section>
      </main>
    </div>
  );
}
