import { ApiError } from './api';

/**
 * Error Handling Utilities
 *
 * Per F6 §9.3 and §13.1, defines standard error handling patterns.
 *
 * NOTE: This module provides backward-compatible error handling utilities.
 * For new code, prefer using ApiError methods directly (e.g., error.userMessage).
 */

/**
 * User-facing error messages (F6 §9.3)
 *
 * These messages are designed to:
 * - Be understandable by non-technical users
 * - Avoid blame-oriented language
 * - Suggest actionable next steps when possible
 */
export const ERROR_MESSAGES = {
  NETWORK: "Couldn't connect. Please try again.",
  SERVER: 'Something went wrong. Please try again.',
  UNAVAILABLE: 'Service temporarily unavailable.',
  NOT_FOUND: 'This item is no longer available.',
  UNAUTHORIZED: 'Session expired.',
  FORBIDDEN: 'Access denied.',
  INVALID_REQUEST: 'Invalid request.',
  GENERIC: 'An unexpected error occurred.',

  // Specific action errors (F3)
  SAVE_FAILED: "Couldn't save. Please try again.",
  SAVE_REPEATED_FAILURE:
    "Having trouble saving. Your work is not lost — please try again in a moment.",
  CONNECTION_LOST: 'Connection lost. Please check your connection.',
  ALREADY_PROCESSED: (action: string) => `Already ${action}`,
} as const;

/**
 * Get user-facing message for an error
 */
export function getErrorMessage(error: unknown): string {
  // Use ApiError's built-in userMessage if available
  if (error instanceof ApiError) {
    return error.userMessage;
  }

  if (error instanceof Error) {
    // Network errors
    if (error.name === 'TypeError' && error.message.includes('fetch')) {
      return ERROR_MESSAGES.NETWORK;
    }
  }

  return ERROR_MESSAGES.GENERIC;
}

/**
 * Check if error should trigger retry (F6 §13.1)
 */
export function shouldRetry(error: unknown): boolean {
  if (error instanceof ApiError) {
    const { status } = error;

    // No retry for client errors
    if (status >= 400 && status < 500) {
      // Exception: 401 can retry with token refresh
      return status === 401;
    }

    // Retry server errors
    return status >= 500;
  }

  // Retry network errors
  return true;
}

/**
 * Check if error is an auth error requiring redirect
 */
export function isAuthError(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.status === 401;
  }
  return false;
}

/**
 * Check if error is a permission error
 */
export function isPermissionError(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.status === 403;
  }
  return false;
}

/**
 * Check if error is a not-found error
 */
export function isNotFoundError(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.status === 404;
  }
  return false;
}

/**
 * Retry configuration per error type (F6 §13.1)
 *
 * | Error Type       | Retry? | Max Retries | Backoff        |
 * |------------------|--------|-------------|----------------|
 * | Network timeout  | Yes    | 3           | 1s, 2s, 5s     |
 * | 500 Internal     | Yes    | 2           | 2s, 5s         |
 * | 503 Unavailable  | Yes    | 3           | 5s, 10s, 30s   |
 * | 400 Bad Request  | No     | —           | —              |
 * | 401 Unauthorized | Yes    | 1           | Immediate      |
 * | 403 Forbidden    | No     | —           | —              |
 * | 404 Not Found    | No     | —           | —              |
 */
export interface RetryConfig {
  maxRetries: number;
  backoffMs: number[];
}

export function getRetryConfig(error: unknown): RetryConfig | null {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 401:
        return { maxRetries: 1, backoffMs: [0] };
      case 500:
        return { maxRetries: 2, backoffMs: [2000, 5000] };
      case 503:
        return { maxRetries: 3, backoffMs: [5000, 10000, 30000] };
      default:
        return null;
    }
  }

  // Network errors
  return { maxRetries: 3, backoffMs: [1000, 2000, 5000] };
}

/**
 * Degradation state derivation (F6 §13.2)
 *
 * | Condition                      | State     |
 * |-------------------------------|-----------|
 * | Single endpoint fails         | Degraded  |
 * | Health endpoint fails         | Degraded  |
 * | All endpoints fail            | Error     |
 * | Evidence fetch fails          | Partial   |
 * | Mutation fails                | Inline    |
 */
export type DegradationState = 'normal' | 'degraded' | 'error' | 'partial' | 'inline';

export interface QueryStatus {
  isError: boolean;
  error: unknown;
}

export function deriveDegradationState(queries: QueryStatus[]): DegradationState {
  const errorCount = queries.filter((q) => q.isError).length;

  if (errorCount === 0) {
    return 'normal';
  }

  if (errorCount === queries.length) {
    return 'error';
  }

  return 'degraded';
}
