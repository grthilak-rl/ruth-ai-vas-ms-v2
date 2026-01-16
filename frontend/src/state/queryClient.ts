import { QueryClient } from '@tanstack/react-query';

/**
 * Query Client Configuration
 *
 * Configures TanStack Query with defaults aligned to F6 error handling rules.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // F6 §13.1: Default retry behavior
      retry: (failureCount, error) => {
        // Type guard for error with status
        const status = (error as { status?: number })?.status;

        // No retry for client errors (4xx)
        if (status && status >= 400 && status < 500) {
          // Exception: 401 gets one retry after token refresh
          if (status === 401 && failureCount < 1) {
            return true;
          }
          return false;
        }

        // Retry server errors up to 3 times
        return failureCount < 3;
      },

      // Stale time: data considered fresh for 30 seconds
      staleTime: 30 * 1000,

      // Cache time: keep data for 5 minutes after unmount
      gcTime: 5 * 60 * 1000,

      // Refetch on window focus (F6 §11.2)
      refetchOnWindowFocus: true,

      // Don't refetch when component remounts if data is fresh
      refetchOnMount: true,

      // Don't refetch on reconnect by default (explicit polling handles this)
      refetchOnReconnect: true,
    },
    mutations: {
      // F6 §13.1: No retry for mutations by default
      retry: false,
    },
  },
});
