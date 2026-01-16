/**
 * Chat Message Component
 *
 * Displays a single message in the chat conversation.
 * Supports user and assistant roles with different styling.
 */

import type { ChatMessage as ChatMessageType } from '../../state';
import { formatExecutionTime } from '../../state';
import './ChatMessage.css';

interface ChatMessageProps {
  message: ChatMessageType;
  /** Show SQL query (for debugging/transparency) */
  showSql?: boolean;
}

/**
 * Individual chat message display.
 *
 * User messages are right-aligned, assistant messages left-aligned.
 * Loading state shows animated dots.
 * Error state shows red styling with error message.
 */
export function ChatMessage({ message, showSql = false }: ChatMessageProps) {
  const isUser = message.role === 'user';
  const isLoading = message.isLoading;
  const hasError = !!message.error;

  return (
    <div
      className={`chat-message chat-message--${message.role} ${hasError ? 'chat-message--error' : ''}`}
    >
      <div className="chat-message__bubble">
        {isLoading ? (
          <span className="chat-message__loading">
            <span className="chat-message__loading-dot"></span>
            <span className="chat-message__loading-dot"></span>
            <span className="chat-message__loading-dot"></span>
          </span>
        ) : (
          <>
            <p className="chat-message__content">{message.content}</p>

            {/* Show generated SQL if enabled and available */}
            {showSql && message.generatedSql && !isUser && (
              <details className="chat-message__sql">
                <summary>View SQL</summary>
                <pre>{message.generatedSql}</pre>
              </details>
            )}

            {/* Metadata for assistant messages */}
            {!isUser && !hasError && message.executionTimeMs && (
              <span className="chat-message__meta">
                {formatExecutionTime(message.executionTimeMs)}
              </span>
            )}
          </>
        )}
      </div>

      <span className="chat-message__timestamp">
        {formatTimestamp(message.timestamp)}
      </span>
    </div>
  );
}

/**
 * Format timestamp for display (HH:MM)
 */
function formatTimestamp(iso: string): string {
  try {
    const date = new Date(iso);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}
