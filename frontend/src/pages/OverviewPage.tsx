import { useAnalyticsQuery } from '../state';
import {
  SummaryCards,
  RecentViolations,
  CameraGrid,
} from '../components/overview';
import { StalenessIndicator } from '../components/ui';
import './OverviewPage.css';

/**
 * Overview Dashboard Page (F4 §4)
 *
 * F2 Path: /
 * Primary landing screen providing operator situational awareness.
 *
 * Per F4 §4.1:
 * - Summary cards: Open Alerts, Cameras Live, Models Active
 * - Recent Violations list (last 5)
 * - Camera Grid (2x2 or 3x2)
 *
 * Per F6:
 * - Each section loads independently
 * - Partial failures do not block other sections
 * - Staleness indicator when data is outdated
 *
 * This dashboard answers: "What is happening in the system right now?"
 */
export function OverviewPage() {
  // Analytics query for staleness indicator
  const { data: analyticsData } = useAnalyticsQuery();

  return (
    <div className="overview-page">
      <header className="overview-page__header">
        <h1 className="overview-page__title">Overview</h1>
        {analyticsData?.generated_at && (
          <StalenessIndicator timestamp={analyticsData.generated_at} />
        )}
      </header>

      <div className="overview-page__content">
        {/* Summary Cards Section */}
        <SummaryCards />

        {/* Main Content Grid */}
        <div className="overview-page__grid">
          {/* Recent Violations (left/main) */}
          <div className="overview-page__main">
            <RecentViolations />
          </div>

          {/* Camera Grid (right/sidebar) */}
          <div className="overview-page__sidebar">
            <CameraGrid />
          </div>
        </div>
      </div>
    </div>
  );
}
