/**
 * Chat Mutation Hook
 *
 * Provides mutation hook for sending chat messages to the NLP Chat Service.
 * Chat is stateless on the server - conversation history is managed locally.
 *
 * Unlike other queries, chat uses mutation because:
 * 1. Each message is a one-off action, not cached data
 * 2. No automatic refetching - user triggers new messages
 * 3. Long timeout (2 minutes) for LLM inference
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '../queryKeys';
import {
  sendChatMessage,
  getChatStatus,
  enableChatService,
  disableChatService,
  generateMessageId,
  formatExecutionTime,
} from '../api/chat.api';
import type {
  ChatRequest,
  ChatResponse,
  ChatStatusResponse,
  ChatMessage,
} from '../api/types';

// ============================================================================
// Chat Status Query
// ============================================================================

/**
 * Check if chat service is enabled and available.
 *
 * Use this to conditionally show/hide chat UI.
 */
export function useChatStatusQuery() {
  return useQuery({
    queryKey: queryKeys.chat.status,
    queryFn: getChatStatus,
    staleTime: 30_000, // Consider status fresh for 30s
    refetchOnWindowFocus: false,
  });
}

// ============================================================================
// Chat Message Mutation
// ============================================================================

/**
 * Options for the chat mutation
 */
export interface UseChatMutationOptions {
  /** Timeout in milliseconds (default: 120000 = 2 minutes) */
  timeout?: number;

  /** Callback when response is received */
  onSuccess?: (response: ChatResponse) => void;

  /** Callback on error */
  onError?: (error: Error) => void;
}

/**
 * Send a chat message mutation hook.
 *
 * Usage:
 * ```tsx
 * const { mutate: sendMessage, isPending } = useChatMutation();
 *
 * const handleSend = (question: string) => {
 *   sendMessage({ question });
 * };
 * ```
 *
 * Note: This mutation does NOT cache responses. Each question is independent.
 * Conversation history should be managed in component state.
 */
export function useChatMutation(options?: UseChatMutationOptions) {
  return useMutation({
    mutationFn: (request: ChatRequest) =>
      sendChatMessage(request, { timeout: options?.timeout }),

    onSuccess: options?.onSuccess,
    onError: options?.onError,

    // Don't retry chat requests - user should retry manually
    retry: false,
  });
}

// ============================================================================
// Chat Service Control Mutations (Admin)
// ============================================================================

/**
 * Enable chat service mutation (admin only).
 */
export function useEnableChatMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: enableChatService,

    // Optimistic update
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: queryKeys.chat.status });

      const previousStatus = queryClient.getQueryData<ChatStatusResponse>(
        queryKeys.chat.status
      );

      queryClient.setQueryData<ChatStatusResponse>(queryKeys.chat.status, {
        enabled: true,
        message: 'Enabling...',
      });

      return { previousStatus };
    },

    onError: (_err, _vars, context) => {
      if (context?.previousStatus) {
        queryClient.setQueryData(queryKeys.chat.status, context.previousStatus);
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.chat.status });
    },
  });
}

/**
 * Disable chat service mutation (admin only).
 */
export function useDisableChatMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: disableChatService,

    // Optimistic update
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: queryKeys.chat.status });

      const previousStatus = queryClient.getQueryData<ChatStatusResponse>(
        queryKeys.chat.status
      );

      queryClient.setQueryData<ChatStatusResponse>(queryKeys.chat.status, {
        enabled: false,
        message: 'Disabling...',
      });

      return { previousStatus };
    },

    onError: (_err, _vars, context) => {
      if (context?.previousStatus) {
        queryClient.setQueryData(queryKeys.chat.status, context.previousStatus);
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.chat.status });
    },
  });
}

// ============================================================================
// Helper Exports
// ============================================================================

/**
 * Create a user message for display.
 */
export function createUserMessage(question: string): ChatMessage {
  return {
    id: generateMessageId(),
    role: 'user',
    content: question,
    timestamp: new Date().toISOString(),
  };
}

/**
 * Create an assistant message from API response.
 */
export function createAssistantMessage(response: ChatResponse): ChatMessage {
  return {
    id: generateMessageId(),
    role: 'assistant',
    content: response.answer,
    timestamp: response.timestamp,
    generatedSql: response.generated_sql,
    executionTimeMs: response.execution_time_ms,
  };
}

/**
 * Create a loading message placeholder.
 */
export function createLoadingMessage(): ChatMessage {
  return {
    id: generateMessageId(),
    role: 'assistant',
    content: '',
    timestamp: new Date().toISOString(),
    isLoading: true,
  };
}

/**
 * Create an error message for display.
 */
export function createErrorMessage(error: Error, question: string): ChatMessage {
  return {
    id: generateMessageId(),
    role: 'assistant',
    content: `Sorry, I couldn't process your question. ${error.message}`,
    timestamp: new Date().toISOString(),
    error: {
      error: 'connection_error',
      message: error.message,
      question,
    },
  };
}

// Re-export utilities
export { generateMessageId, formatExecutionTime };

// Re-export types
export type { ChatRequest, ChatResponse, ChatStatusResponse, ChatMessage };
