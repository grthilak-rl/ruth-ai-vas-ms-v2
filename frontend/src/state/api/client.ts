/**
 * Centralized API Client
 *
 * ALL network access MUST flow through this module.
 * No component or hook may call fetch() directly.
 *
 * Features:
 * - Auth header attachment
 * - Request timeout handling
 * - Error normalization
 * - Retry/backoff per F6 §13.1
 *
 * This is the ONLY allowed way the frontend talks to the backend.
 */

import { buildApiUrl } from '../../config/api';
import {
  ApiError,
  createApiErrorFromResponse,
  createNetworkError,
} from './errors';

// ============================================================================
// Configuration
// ============================================================================

/** Default request timeout in milliseconds */
const DEFAULT_TIMEOUT_MS = 30_000;

/** Token storage key */
const TOKEN_KEY = 'auth_token';

/**
 * Retry configuration per error type (F6 §13.1)
 *
 * | Error Type       | Retries | Backoff           |
 * |------------------|---------|-------------------|
 * | Network timeout  | 3       | 1s → 2s → 5s      |
 * | 500 Internal     | 2       | 2s → 5s           |
 * | 503 Unavailable  | 3       | 5s → 10s → 30s    |
 * | 401 Unauthorized | 1       | immediate         |
 */
const RETRY_CONFIG: Record<number | 'network', { maxRetries: number; backoffMs: number[] }> = {
  network: { maxRetries: 3, backoffMs: [1000, 2000, 5000] },
  500: { maxRetries: 2, backoffMs: [2000, 5000] },
  502: { maxRetries: 3, backoffMs: [5000, 10000, 30000] },
  503: { maxRetries: 3, backoffMs: [5000, 10000, 30000] },
  504: { maxRetries: 3, backoffMs: [5000, 10000, 30000] },
  401: { maxRetries: 1, backoffMs: [0] },
};

// ============================================================================
// Request Options
// ============================================================================

export interface RequestOptions {
  /** Request timeout in milliseconds (default: 30000) */
  timeout?: number;

  /** Whether to skip retry logic (default: false) */
  skipRetry?: boolean;

  /** Custom headers to merge */
  headers?: Record<string, string>;

  /** AbortSignal for cancellation */
  signal?: AbortSignal;
}

export interface RequestResult<T> {
  /** Response data if successful */
  data: T;

  /** HTTP status code */
  status: number;

  /** Response headers */
  headers: Headers;
}

// ============================================================================
// Internal Utilities
// ============================================================================

/**
 * Get auth token from storage
 */
function getAuthToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    // localStorage may not be available (SSR, privacy mode)
    return null;
  }
}

/**
 * Build request headers with auth
 */
function buildHeaders(customHeaders?: Record<string, string>): Headers {
  const headers = new Headers({
    'Content-Type': 'application/json',
    Accept: 'application/json',
  });

  const token = getAuthToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  if (customHeaders) {
    Object.entries(customHeaders).forEach(([key, value]) => {
      headers.set(key, value);
    });
  }

  return headers;
}

/**
 * Create abort controller with timeout
 */
function createTimeoutController(
  timeoutMs: number,
  existingSignal?: AbortSignal
): { controller: AbortController; cleanup: () => void } {
  const controller = new AbortController();

  const timeoutId = setTimeout(() => {
    controller.abort(new Error('Request timeout'));
  }, timeoutMs);

  // If there's an existing signal, abort when it aborts
  if (existingSignal) {
    if (existingSignal.aborted) {
      controller.abort(existingSignal.reason);
    } else {
      existingSignal.addEventListener('abort', () => {
        controller.abort(existingSignal.reason);
      });
    }
  }

  const cleanup = () => clearTimeout(timeoutId);

  return { controller, cleanup };
}

/**
 * Get retry configuration for a status code
 */
function getRetryConfig(status: number): { maxRetries: number; backoffMs: number[] } | null {
  if (status === 0) {
    return RETRY_CONFIG.network;
  }

  if (status in RETRY_CONFIG) {
    return RETRY_CONFIG[status as keyof typeof RETRY_CONFIG];
  }

  // Default: no retry for unlisted status codes
  return null;
}

/**
 * Sleep for specified milliseconds
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ============================================================================
// Core Fetch Function
// ============================================================================

/**
 * Execute a single fetch request (no retry)
 */
async function executeFetch<T>(
  url: string,
  init: RequestInit,
  options: RequestOptions
): Promise<RequestResult<T>> {
  const timeoutMs = options.timeout ?? DEFAULT_TIMEOUT_MS;
  const { controller, cleanup } = createTimeoutController(timeoutMs, options.signal);

  try {
    const response = await fetch(url, {
      ...init,
      signal: controller.signal,
    });

    if (!response.ok) {
      const error = await createApiErrorFromResponse(response);
      throw error;
    }

    // Parse JSON response
    const data = (await response.json()) as T;

    return {
      data,
      status: response.status,
      headers: response.headers,
    };
  } catch (error) {
    // Already an ApiError, rethrow
    if (error instanceof ApiError) {
      throw error;
    }

    // Network/timeout error
    if (error instanceof Error) {
      throw createNetworkError(error);
    }

    // Unknown error
    throw createNetworkError(new Error(String(error)));
  } finally {
    cleanup();
  }
}

/**
 * Execute fetch with retry logic (F6 §13.1)
 *
 * Retries are VISIBLE to callers - errors include retry count info.
 * Retries are NOT hidden from the system.
 */
async function fetchWithRetry<T>(
  url: string,
  init: RequestInit,
  options: RequestOptions
): Promise<RequestResult<T>> {
  if (options.skipRetry) {
    return executeFetch<T>(url, init, options);
  }

  let lastError: ApiError | null = null;
  let attempt = 0;

  // First attempt (not a retry)
  try {
    return await executeFetch<T>(url, init, options);
  } catch (error) {
    if (!(error instanceof ApiError)) {
      throw error;
    }
    lastError = error;
  }

  // Check if retryable
  if (!lastError.retryable) {
    throw lastError;
  }

  const retryConfig = getRetryConfig(lastError.status);
  if (!retryConfig) {
    throw lastError;
  }

  // Retry loop
  while (attempt < retryConfig.maxRetries) {
    const backoffMs = retryConfig.backoffMs[attempt] ?? retryConfig.backoffMs[retryConfig.backoffMs.length - 1];

    // Log retry attempt for observability (not hidden)
    console.warn(
      `[API] Retry ${attempt + 1}/${retryConfig.maxRetries} after ${backoffMs}ms for ${url}`
    );

    await sleep(backoffMs);
    attempt++;

    try {
      return await executeFetch<T>(url, init, options);
    } catch (error) {
      if (!(error instanceof ApiError)) {
        throw error;
      }
      lastError = error;

      // Stop retrying if error is no longer retryable
      if (!error.retryable) {
        throw error;
      }
    }
  }

  // All retries exhausted
  console.error(`[API] All ${retryConfig.maxRetries} retries exhausted for ${url}`);
  throw lastError;
}

// ============================================================================
// Public API (READ-ONLY for E3)
// ============================================================================

/**
 * GET request
 *
 * This is the PRIMARY method for E3 read-only API access.
 */
export async function apiGet<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const url = buildApiUrl(path);

  const result = await fetchWithRetry<T>(url, {
    method: 'GET',
    headers: buildHeaders(options.headers),
  }, options);

  return result.data;
}

/**
 * GET request with full result (includes headers, status)
 *
 * Use when you need response metadata.
 */
export async function apiGetFull<T>(
  path: string,
  options: RequestOptions = {}
): Promise<RequestResult<T>> {
  const url = buildApiUrl(path);

  return fetchWithRetry<T>(url, {
    method: 'GET',
    headers: buildHeaders(options.headers),
  }, options);
}

// ============================================================================
// Write Methods (E5+)
// ============================================================================

/**
 * PATCH request
 *
 * Used for updating resources (e.g., violation status).
 * F6 §10.1: Optimistic update with rollback on failure.
 */
export async function apiPatch<T>(
  path: string,
  body: unknown,
  options: RequestOptions = {}
): Promise<T> {
  const url = buildApiUrl(path);

  const result = await fetchWithRetry<T>(url, {
    method: 'PATCH',
    headers: buildHeaders(options.headers),
    body: JSON.stringify(body),
  }, options);

  return result.data;
}

/**
 * POST request
 *
 * Used for creating resources.
 */
export async function apiPost<T>(
  path: string,
  body: unknown,
  options: RequestOptions = {}
): Promise<T> {
  const url = buildApiUrl(path);

  const result = await fetchWithRetry<T>(url, {
    method: 'POST',
    headers: buildHeaders(options.headers),
    body: JSON.stringify(body),
  }, options);

  return result.data;
}

// ============================================================================
// Re-export error types for consumers
// ============================================================================

export { ApiError } from './errors';
export type { ApiErrorCategory } from './errors';
