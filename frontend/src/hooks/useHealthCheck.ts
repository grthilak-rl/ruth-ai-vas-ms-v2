import { useEffect, useRef } from 'react';
import { apiConfig, buildApiUrl } from '../config/api';

interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

/**
 * Health Check Hook
 *
 * Performs a single health check on app load.
 * Per E1 spec:
 * - Calls GET /health once on app load
 * - Logs result to console only
 * - Does not display health in UI yet
 * - Verifies API connectivity and environment configuration
 */
export function useHealthCheck(): void {
  const hasChecked = useRef(false);

  useEffect(() => {
    // Only run once
    if (hasChecked.current) {
      return;
    }
    hasChecked.current = true;

    const checkHealth = async () => {
      const url = buildApiUrl(apiConfig.healthEndpoint);

      try {
        const response = await fetch(url);

        if (!response.ok) {
          console.warn(
            '[HealthCheck] Backend returned non-OK status:',
            response.status
          );
          return;
        }

        const data: HealthResponse = await response.json();
        console.log('[HealthCheck] Backend health check successful:', data);
      } catch (error) {
        console.error('[HealthCheck] Failed to connect to backend:', error);
      }
    };

    checkHealth();
  }, []);
}
