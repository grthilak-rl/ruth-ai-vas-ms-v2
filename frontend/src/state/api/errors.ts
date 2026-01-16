/**
 * API Error Model
 *
 * Normalized error types for API responses.
 * All errors are explicit and testable - no hidden failures.
 *
 * Per F6 §9.3 and §13.1
 */

/**
 * Error categories for classification
 */
export type ApiErrorCategory =
  | 'network' // Network failure, timeout
  | 'client' // 4xx errors
  | 'server' // 5xx errors
  | 'auth' // 401/403 specifically
  | 'not_found' // 404 specifically
  | 'unknown'; // Unclassified

/**
 * Structured API error with full context
 */
export class ApiError extends Error {
  /** HTTP status code (0 for network errors) */
  public readonly status: number;

  /** Error category for handling decisions */
  public readonly category: ApiErrorCategory;

  /** Backend error code if provided */
  public readonly code?: string;

  /** Whether this error is retryable */
  public readonly retryable: boolean;

  /** User-facing message (F6 §9.3 compliant) */
  public readonly userMessage: string;

  /** Original error for debugging (never exposed to UI) */
  public readonly originalError?: Error;

  constructor(params: {
    status: number;
    message: string;
    category: ApiErrorCategory;
    code?: string;
    retryable: boolean;
    userMessage: string;
    originalError?: Error;
  }) {
    super(params.message);
    this.name = 'ApiError';
    this.status = params.status;
    this.category = params.category;
    this.code = params.code;
    this.retryable = params.retryable;
    this.userMessage = params.userMessage;
    this.originalError = params.originalError;
  }

  /**
   * Check if error is an authentication error (401)
   */
  isAuthError(): boolean {
    return this.status === 401;
  }

  /**
   * Check if error is a permission error (403)
   */
  isPermissionError(): boolean {
    return this.status === 403;
  }

  /**
   * Check if error is not found (404)
   */
  isNotFoundError(): boolean {
    return this.status === 404;
  }

  /**
   * Check if error is a server error (5xx)
   */
  isServerError(): boolean {
    return this.status >= 500 && this.status < 600;
  }

  /**
   * Check if error is a network error
   */
  isNetworkError(): boolean {
    return this.category === 'network';
  }
}

/**
 * User-facing error messages (F6 §9.3)
 *
 * These messages are designed to:
 * - Be understandable by non-technical users
 * - Avoid blame-oriented language (F3 constraint)
 * - Suggest actionable next steps when possible
 */
export const USER_MESSAGES = {
  NETWORK: "Couldn't connect. Please try again.",
  TIMEOUT: "Request timed out. Please try again.",
  SERVER: 'Something went wrong. Please try again.',
  UNAVAILABLE: 'Service temporarily unavailable.',
  NOT_FOUND: 'This item is no longer available.',
  UNAUTHORIZED: 'Session expired.',
  FORBIDDEN: 'Access denied.',
  BAD_REQUEST: 'Invalid request.',
  UNKNOWN: 'An unexpected error occurred.',
} as const;

/**
 * Classify HTTP status to error category
 */
export function classifyStatus(status: number): ApiErrorCategory {
  if (status === 0) return 'network';
  if (status === 401 || status === 403) return 'auth';
  if (status === 404) return 'not_found';
  if (status >= 400 && status < 500) return 'client';
  if (status >= 500) return 'server';
  return 'unknown';
}

/**
 * Get user message for HTTP status (F6 §9.3)
 */
export function getUserMessageForStatus(status: number): string {
  switch (status) {
    case 0:
      return USER_MESSAGES.NETWORK;
    case 400:
      return USER_MESSAGES.BAD_REQUEST;
    case 401:
      return USER_MESSAGES.UNAUTHORIZED;
    case 403:
      return USER_MESSAGES.FORBIDDEN;
    case 404:
      return USER_MESSAGES.NOT_FOUND;
    case 500:
      return USER_MESSAGES.SERVER;
    case 502:
    case 503:
    case 504:
      return USER_MESSAGES.UNAVAILABLE;
    default:
      if (status >= 500) return USER_MESSAGES.SERVER;
      return USER_MESSAGES.UNKNOWN;
  }
}

/**
 * Determine if status code is retryable (F6 §13.1)
 *
 * | Error Type       | Retryable |
 * |------------------|-----------|
 * | Network timeout  | Yes       |
 * | 500 Internal     | Yes       |
 * | 503 Unavailable  | Yes       |
 * | 400 Bad Request  | No        |
 * | 401 Unauthorized | Yes (1x)  |
 * | 403 Forbidden    | No        |
 * | 404 Not Found    | No        |
 */
export function isStatusRetryable(status: number): boolean {
  // Network error
  if (status === 0) return true;

  // Server errors are retryable
  if (status >= 500) return true;

  // 401 gets one retry (with token refresh)
  if (status === 401) return true;

  // All other client errors are not retryable
  return false;
}

/**
 * Create ApiError from fetch response
 */
export async function createApiErrorFromResponse(
  response: Response,
  originalError?: Error
): Promise<ApiError> {
  const status = response.status;
  const category = classifyStatus(status);
  const userMessage = getUserMessageForStatus(status);
  const retryable = isStatusRetryable(status);

  let message = `HTTP ${status}`;
  let code: string | undefined;

  // Try to extract error details from response body
  try {
    const body = await response.json();
    if (body.message) message = body.message;
    if (body.code) code = body.code;
    if (body.error) message = body.error;
  } catch {
    // Response body not JSON, use status text
    message = response.statusText || message;
  }

  return new ApiError({
    status,
    message,
    category,
    code,
    retryable,
    userMessage,
    originalError,
  });
}

/**
 * Create ApiError from network/fetch error
 */
export function createNetworkError(error: Error): ApiError {
  const isTimeout =
    error.name === 'AbortError' || error.message.includes('timeout');

  return new ApiError({
    status: 0,
    message: error.message,
    category: 'network',
    retryable: true,
    userMessage: isTimeout ? USER_MESSAGES.TIMEOUT : USER_MESSAGES.NETWORK,
    originalError: error,
  });
}
