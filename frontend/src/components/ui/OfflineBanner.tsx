import { useOnlineStatus } from './useOnlineStatus';
import './OfflineBanner.css';

interface OfflineBannerProps {
  /** Optional custom message */
  message?: string;
}

/**
 * Offline Banner Component (E9)
 *
 * Global indicator when network connectivity is lost.
 *
 * Per E9 Offline Handling:
 * - Display offline banner/indicator
 * - Preserve last known data
 * - Auto-recover when connectivity returns
 *
 * Per F3 Flow 3.3:
 * - Global status: "Connection lost"
 * - "Couldn't reach server. Please check your connection."
 *
 * HARD RULES (E9):
 * - Never trap the user
 * - Never block navigation
 * - Auto-recover when possible
 */
export function OfflineBanner({ message }: OfflineBannerProps) {
  const { isOnline, wasOffline } = useOnlineStatus();

  // Show recovery message briefly after coming back online
  if (isOnline && wasOffline) {
    return (
      <div
        className="offline-banner offline-banner--recovered"
        role="status"
        aria-live="polite"
      >
        <span className="offline-banner__icon" aria-hidden="true">
          ✓
        </span>
        <span className="offline-banner__text">Connection restored</span>
      </div>
    );
  }

  // Only show when offline
  if (isOnline) {
    return null;
  }

  return (
    <div
      className="offline-banner offline-banner--offline"
      role="alert"
      aria-live="assertive"
    >
      <span className="offline-banner__icon" aria-hidden="true">
        ○
      </span>
      <span className="offline-banner__text">
        {message || 'Connection lost. Please check your network.'}
      </span>
    </div>
  );
}
