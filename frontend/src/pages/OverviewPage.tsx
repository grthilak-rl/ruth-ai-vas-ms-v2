import {
  TopStatusBar,
  RecentViolations,
  CameraGrid,
  HardwareCapacityCard,
} from '../components/overview';
import { ChatPanel } from '../components/chat';
import './OverviewPage.css';

/**
 * Overview Dashboard Page (F4 §4)
 *
 * F2 Path: /
 * Primary landing screen providing operator situational awareness.
 *
 * Layout (compact, no-scroll design):
 * ┌──────────────────────────────────────────────────────────────────────────┐
 * │ Row 1: [Open Alerts] [Cameras Live] [Models Active] | [System Health]   │
 * ├──────────────────────────────────────────────────────────────────────────┤
 * │ Row 2:                                                                   │
 * │   Left Column:              │  Right Column:                             │
 * │   ┌─────────────────────┐   │  ┌─────────────────────────────────────┐   │
 * │   │ Recent Violations   │   │  │ Ask Ruth                            │   │
 * │   │ (4 entries max)     │   │  │                                     │   │
 * │   └─────────────────────┘   │  │                                     │   │
 * │   ┌─────────────────────┐   │  ├─────────────────────────────────────┤   │
 * │   │ Hardware Capacity   │   │  │ Camera Grid                         │   │
 * │   │                     │   │  │                                     │   │
 * │   └─────────────────────┘   │  └─────────────────────────────────────┘   │
 * └──────────────────────────────────────────────────────────────────────────┘
 *
 * Per F6:
 * - Each section loads independently
 * - Partial failures do not block other sections
 *
 * This dashboard answers: "What is happening in the system right now?"
 */
export function OverviewPage() {
  return (
    <div className="overview-page">
      {/* Top Status Bar: Summary metrics + Health indicators */}
      <TopStatusBar />

      {/* Main Content: Two-column layout */}
      <div className="overview-page__content">
        {/* Left Column: Recent Violations + Hardware Capacity */}
        <div className="overview-page__left">
          <RecentViolations />
          <HardwareCapacityCard />
        </div>

        {/* Right Column: Ask Ruth + Camera Grid */}
        <div className="overview-page__right">
          <div className="overview-page__chat">
            <ChatPanel showSql={false} />
          </div>
          <div className="overview-page__cameras">
            <CameraGrid />
          </div>
        </div>
      </div>
    </div>
  );
}
