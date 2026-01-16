/**
 * Chat API
 *
 * API for NLP Chat Service integration.
 *
 * Source Endpoints:
 * - POST /api/v1/chat
 * - GET /api/v1/chat/status
 * - POST /api/v1/chat/enable
 * - POST /api/v1/chat/disable
 *
 * The chat service allows users to ask natural language questions
 * about Ruth AI data (violations, devices, events, etc.) and get
 * AI-generated answers.
 */

import { apiGet, apiPost } from './client';
import type {
  ChatRequest,
  ChatResponse,
  ChatStatusResponse,
} from './types';

/** API paths for chat */
const CHAT_PATH = '/api/v1/chat';
const CHAT_STATUS_PATH = '/api/v1/chat/status';
const CHAT_ENABLE_PATH = '/api/v1/chat/enable';
const CHAT_DISABLE_PATH = '/api/v1/chat/disable';

/**
 * Send a chat message (ask a question)
 *
 * Sends a natural language question to the NLP Chat Service
 * and returns an AI-generated answer.
 *
 * @param request - Chat request with question
 * @param options - Request options (timeout, etc.)
 * @returns Chat response with answer
 *
 * @example
 * ```ts
 * const response = await sendChatMessage({
 *   question: "How many violations are there?",
 *   include_raw_data: false
 * });
 * console.log(response.answer); // "There are 6 violations in the system."
 * ```
 */
export async function sendChatMessage(
  request: ChatRequest,
  options?: { timeout?: number; signal?: AbortSignal }
): Promise<ChatResponse> {
  // Use a longer timeout for chat requests since LLM inference can be slow
  const response = await apiPost<ChatResponse>(
    CHAT_PATH,
    request,
    {
      timeout: options?.timeout ?? 120_000, // 2 minutes default for chat
      signal: options?.signal,
      skipRetry: true, // Don't retry chat requests - user should retry manually
    }
  );

  return response;
}

/**
 * Get chat service status
 *
 * Checks if the NLP Chat Service is enabled and available.
 *
 * @returns Status response indicating if service is enabled
 */
export async function getChatStatus(): Promise<ChatStatusResponse> {
  const response = await apiGet<ChatStatusResponse>(CHAT_STATUS_PATH);
  return response;
}

/**
 * Enable chat service
 *
 * Admin action to enable the NLP Chat Service.
 *
 * @returns Updated status
 */
export async function enableChatService(): Promise<ChatStatusResponse> {
  const response = await apiPost<ChatStatusResponse>(CHAT_ENABLE_PATH, {});
  return response;
}

/**
 * Disable chat service
 *
 * Admin action to disable the NLP Chat Service.
 *
 * @returns Updated status
 */
export async function disableChatService(): Promise<ChatStatusResponse> {
  const response = await apiPost<ChatStatusResponse>(CHAT_DISABLE_PATH, {});
  return response;
}

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Generate a unique message ID
 */
export function generateMessageId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
}

/**
 * Format execution time for display
 *
 * @param ms - Execution time in milliseconds
 * @returns Human-readable string
 */
export function formatExecutionTime(ms: number): string {
  if (ms < 1000) {
    return `${ms}ms`;
  }
  return `${(ms / 1000).toFixed(1)}s`;
}

// ============================================================================
// Re-exports for consumers
// ============================================================================

export type {
  ChatRequest,
  ChatResponse,
  ChatStatusResponse,
  ChatErrorDetail,
  ChatMessage,
} from './types';
