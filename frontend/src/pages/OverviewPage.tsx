import {
  TopStatusBar,
  SystemHealthCard,
  RecentViolations,
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
 * │ Row 1: [Open Alerts] [Cameras Live] [Models Active] | [Camera Grid]      │
 * ├──────────────────────────────────────────────────────────────────────────┤
 * │ Row 2:                                                                   │
 * │   Left Column:              │  Right Column:                             │
 * │   ┌─────────────────────┐   │  ┌─────────────────────────────────────┐   │
 * │   │ System Health       │   │  │ Ask Ruth                            │   │
 * │   │                     │   │  │                                     │   │
 * │   └─────────────────────┘   │  │                                     │   │
 * │   ┌─────────────────────┐   │  ├─────────────────────────────────────┤   │
 * │   │ Hardware Capacity   │   │  │ Recent Violations                   │   │
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
      {/* Top Status Bar: Summary metrics + Camera Grid */}
      <TopStatusBar />

      {/* Main Content: Two-column layout */}
      <div className="overview-page__content">
        {/* Left Column: System Health + Hardware Capacity */}
        <div className="overview-page__left">
          <SystemHealthCard />
          <HardwareCapacityCard />
        </div>

        {/* Right Column: Ask Ruth + Recent Violations */}
        <div className="overview-page__right">
          <div className="overview-page__chat">
            <ChatPanel showSql={false} />
          </div>
          <div className="overview-page__violations">
            <RecentViolations />
          </div>
        </div>
      </div>
    </div>
  );
}
