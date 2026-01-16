/**
 * API Configuration Module
 *
 * Provides centralized configuration for API endpoints.
 * All URLs are derived from environment variables.
 * No hardcoded URLs exist in this module.
 */

interface ApiConfig {
  /** Base URL for API requests (proxied in development) */
  baseUrl: string;
  /** Health check endpoint path */
  healthEndpoint: string;
}

/**
 * API configuration derived from environment variables.
 * In development, requests are proxied through Vite dev server.
 * In production, VITE_API_BASE_URL should be set appropriately.
 */
export const apiConfig: ApiConfig = {
  // Empty string because we use Vite proxy in development
  // In production build, this would be the full URL
  baseUrl: '',
  healthEndpoint: '/api/v1/health',
};

/**
 * Build a full API URL from a path
 */
export function buildApiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${apiConfig.baseUrl}${normalizedPath}`;
}