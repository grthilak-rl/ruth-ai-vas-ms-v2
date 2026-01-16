import { useState, useEffect, useCallback } from 'react';

interface OnlineStatusResult {
  /** Whether the browser is online */
  isOnline: boolean;
  /** Whether we've detected being offline at any point */
  wasOffline: boolean;
  /** Manually trigger a reconnection check */
  checkConnection: () => Promise<boolean>;
}

/**
 * Hook for tracking browser online/offline status (E9)
 *
 * Per E9 Offline Handling:
 * - Detect network loss
 * - Auto-recover when connectivity returns
 * - Never trap the user
 *
 * Per F3 Flow 3.3 - Network offline during action:
 * - "Connection lost" global status
 * - "Couldn't reach server. Please check your connection."
 *
 * HARD RULES (E9):
 * - Offline mode must never trap the user
 * - Never block navigation
 * - Never silently discard actions
 */
export function useOnlineStatus(): OnlineStatusResult {
  const [isOnline, setIsOnline] = useState(
    typeof navigator !== 'undefined' ? navigator.onLine : true
  );
  const [wasOffline, setWasOffline] = useState(false);

  // Handle online event
  const handleOnline = useCallback(() => {
    setIsOnline(true);
  }, []);

  // Handle offline event
  const handleOffline = useCallback(() => {
    setIsOnline(false);
    setWasOffline(true);
  }, []);

  // Manual connection check
  const checkConnection = useCallback(async (): Promise<boolean> => {
    if (typeof navigator !== 'undefined' && !navigator.onLine) {
      setIsOnline(false);
      return false;
    }

    // Try to fetch a small resource to verify actual connectivity
    try {
      // Use the health endpoint as a connectivity check
      const response = await fetch('/api/v1/health', {
        method: 'HEAD',
        cache: 'no-store',
      });
      const online = response.ok;
      setIsOnline(online);
      return online;
    } catch {
      setIsOnline(false);
      return false;
    }
  }, []);

  // Set up event listeners
  useEffect(() => {
    if (typeof window === 'undefined') return;

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, [handleOnline, handleOffline]);

  return {
    isOnline,
    wasOffline,
    checkConnection,
  };
}
