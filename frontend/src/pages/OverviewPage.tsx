import {
  TopStatusBar,
  RecentViolations,
  CameraGrid,
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
 * ┌─────────────────────────────────────────────────────────────────┐
 * │ [Open Alerts] [Cameras] [Models]              System: ●●●●●    │
 * ├─────────────────────────────────┬───────────────────────────────┤
 * │                                 │                               │
 * │   Recent Violations             │   Ask Ruth (compact chat)     │
 * │   (last 5 alerts)               │   [suggestion chips]          │
 * │                                 │   [input field]               │
 * │                                 ├───────────────────────────────┤
 * │                                 │   Camera Grid (2x3)           │
 * │                                 │   compact status tiles        │
 * │                                 │                               │
 * └─────────────────────────────────┴───────────────────────────────┘
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
        {/* Left Column: Recent Violations */}
        <div className="overview-page__left">
          <RecentViolations />
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
