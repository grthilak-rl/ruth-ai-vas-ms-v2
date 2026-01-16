/**
 * Chat Panel Component
 *
 * Provides a chat interface for natural language queries about Ruth AI data.
 * Uses the NLP Chat Service to answer questions about violations, devices, etc.
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import {
  useChatMutation,
  useChatStatusQuery,
  createUserMessage,
  createAssistantMessage,
  createLoadingMessage,
  createErrorMessage,
  type ChatMessage as ChatMessageType,
} from '../../state';
import { ChatMessage } from './ChatMessage';
import './ChatPanel.css';

interface ChatPanelProps {
  /** Whether to show SQL queries in responses */
  showSql?: boolean;
  /** Placeholder text for input */
  placeholder?: string;
  /** Panel title */
  title?: string;
}

/**
 * Chat Panel for natural language queries.
 *
 * Features:
 * - Message history (local state, not persisted)
 * - Auto-scroll on new messages
 * - Loading state while waiting for response
 * - Error handling with retry option
 * - Optional SQL display for transparency
 *
 * Example questions:
 * - "How many violations are there?"
 * - "Show me open violations"
 * - "List all devices"
 */
export function ChatPanel({
  showSql = false,
  placeholder = 'Ask about violations, cameras, events...',
  title = 'Ask Ruth',
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Check if chat service is available
  const { data: statusData, isLoading: isStatusLoading } = useChatStatusQuery();
  const isServiceEnabled = statusData?.enabled ?? true; // Assume enabled if status unknown

  // Chat mutation
  const chatMutation = useChatMutation({
    onSuccess: (response) => {
      // Replace loading message with actual response
      setMessages((prev) => {
        const updated = [...prev];
        // Find last loading message (iterate backwards)
        let loadingIndex = -1;
        for (let i = updated.length - 1; i >= 0; i--) {
          if (updated[i].isLoading) {
            loadingIndex = i;
            break;
          }
        }
        if (loadingIndex !== -1) {
          updated[loadingIndex] = createAssistantMessage(response);
        }
        return updated;
      });
    },
    onError: (error) => {
      // Replace loading message with error
      setMessages((prev) => {
        const updated = [...prev];
        // Find last loading message (iterate backwards)
        let loadingIndex = -1;
        for (let i = updated.length - 1; i >= 0; i--) {
          if (updated[i].isLoading) {
            loadingIndex = i;
            break;
          }
        }
        if (loadingIndex !== -1) {
          const userMessage = updated[loadingIndex - 1];
          updated[loadingIndex] = createErrorMessage(
            error,
            userMessage?.content ?? 'Unknown question'
          );
        }
        return updated;
      });
    },
  });

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Handle form submission
  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const question = input.trim();
      if (!question || chatMutation.isPending) return;

      // Add user message
      const userMsg = createUserMessage(question);
      // Add loading placeholder
      const loadingMsg = createLoadingMessage();

      setMessages((prev) => [...prev, userMsg, loadingMsg]);
      setInput('');

      // Send to API
      chatMutation.mutate({
        question,
        include_raw_data: false,
      });
    },
    [input, chatMutation]
  );

  // Handle key press (Enter to send)
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      handleSubmit(e);
    }
  };

  // Clear chat history
  const handleClear = () => {
    setMessages([]);
    inputRef.current?.focus();
  };

  return (
    <div className="chat-panel">
      <header className="chat-panel__header">
        <h3 className="chat-panel__title">{title}</h3>
        {messages.length > 0 && (
          <button
            type="button"
            className="chat-panel__clear-btn"
            onClick={handleClear}
            aria-label="Clear chat"
          >
            Clear
          </button>
        )}
      </header>

      <div className="chat-panel__messages">
        {messages.length === 0 ? (
          <div className="chat-panel__empty">
            <p className="chat-panel__empty-title">Ask me anything</p>
            <p className="chat-panel__empty-hint">
              I can help you find information about violations, cameras, and events.
            </p>
            <div className="chat-panel__examples">
              <button
                type="button"
                className="chat-panel__example"
                onClick={() => setInput('How many violations are there?')}
              >
                How many violations?
              </button>
              <button
                type="button"
                className="chat-panel__example"
                onClick={() => setInput('Show me open violations')}
              >
                Open violations
              </button>
              <button
                type="button"
                className="chat-panel__example"
                onClick={() => setInput('List all devices')}
              >
                List devices
              </button>
            </div>
          </div>
        ) : (
          messages.map((msg) => (
            <ChatMessage key={msg.id} message={msg} showSql={showSql} />
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <form className="chat-panel__form" onSubmit={handleSubmit}>
        {!isServiceEnabled && !isStatusLoading && (
          <div className="chat-panel__disabled-notice">
            Chat service is currently disabled
          </div>
        )}
        <div className="chat-panel__input-row">
          <input
            ref={inputRef}
            type="text"
            className="chat-panel__input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={chatMutation.isPending || !isServiceEnabled}
            aria-label="Chat message"
          />
          <button
            type="submit"
            className="chat-panel__send-btn"
            disabled={!input.trim() || chatMutation.isPending || !isServiceEnabled}
            aria-label="Send message"
          >
            {chatMutation.isPending ? (
              <span className="chat-panel__send-spinner" />
            ) : (
              <SendIcon />
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

/**
 * Send icon SVG
 */
function SendIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="currentColor"
      width="20"
      height="20"
    >
      <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
    </svg>
  );
}
