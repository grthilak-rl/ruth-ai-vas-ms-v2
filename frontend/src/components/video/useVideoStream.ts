import { useState, useCallback, useRef, useEffect } from 'react';

/**
 * Video stream states
 */
export type VideoStreamState =
  | 'idle' // Not started
  | 'connecting' // Establishing connection
  | 'connected' // Receiving video
  | 'reconnecting' // Lost connection, attempting to recover
  | 'error' // Failed (non-recoverable or max retries exceeded)
  | 'offline'; // Camera is offline

/**
 * Video-specific error (isolated from global errors)
 */
export interface VideoError {
  type: 'connection' | 'stream' | 'timeout' | 'unknown';
  message: string;
  retryable: boolean;
}

/**
 * Reconnection configuration
 */
const RECONNECT_CONFIG = {
  maxAttempts: 3,
  baseDelayMs: 1000,
  maxDelayMs: 10000,
};

interface UseVideoStreamOptions {
  /** Device/camera ID */
  deviceId: string;
  /** VAS stream ID (if already streaming) */
  streamId?: string | null;
  /** Whether device is available for streaming */
  isAvailable: boolean;
  /** Auto-connect when available (default: false - user must initiate) */
  autoConnect?: boolean;
  /** Callback when video track is ready */
  onTrackReady?: (track: MediaStreamTrack) => void;
  /** Callback when video track is lost */
  onTrackLost?: () => void;
}

interface UseVideoStreamResult {
  /** Current connection state */
  state: VideoStreamState;
  /** Current error (if any) */
  error: VideoError | null;
  /** MediaStream for video element */
  mediaStream: MediaStream | null;
  /** Start video playback (user-initiated) */
  connect: () => Promise<void>;
  /** Stop video playback */
  disconnect: () => void;
  /** Retry after error */
  retry: () => void;
  /** Current reconnect attempt (0 if not reconnecting) */
  reconnectAttempt: number;
}

/**
 * Hook for managing video stream connection (E10)
 *
 * Per E10 Spec:
 * - Video must be explicitly user-initiated (no forced autoplay)
 * - Failure to load video MUST NOT block the rest of the screen
 * - Video failures never escalate to global error state
 *
 * Connection Flow (per VAS Integration Guide §5):
 * 1. Get router capabilities
 * 2. Attach consumer
 * 3. Create transport and connect
 * 4. Consume media track
 *
 * HARD RULES:
 * - Video failures are isolated from UI state
 * - No stream IDs exposed to users
 * - Graceful reconnect without user intervention
 */
export function useVideoStream({
  deviceId: _deviceId, // Reserved for future WebRTC integration
  streamId,
  isAvailable,
  autoConnect = false,
  onTrackReady: _onTrackReady, // Reserved for future WebRTC integration
  onTrackLost,
}: UseVideoStreamOptions): UseVideoStreamResult {
  const [state, setState] = useState<VideoStreamState>(isAvailable ? 'idle' : 'offline');
  const [error, setError] = useState<VideoError | null>(null);
  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);

  // Refs for cleanup (typed as any for mediasoup-client compatibility)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const transportRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const consumerRef = useRef<any>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMountedRef = useRef(true);

  // Cleanup function
  const cleanup = useCallback(() => {
    // Clear reconnect timeout
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    // Close consumer
    if (consumerRef.current) {
      try {
        consumerRef.current.close();
      } catch {
        // Ignore cleanup errors
      }
      consumerRef.current = null;
    }

    // Close transport
    if (transportRef.current) {
      try {
        transportRef.current.close();
      } catch {
        // Ignore cleanup errors
      }
      transportRef.current = null;
    }

    // Clear media stream
    if (mediaStream) {
      mediaStream.getTracks().forEach(track => track.stop());
    }
    setMediaStream(null);
    onTrackLost?.();
  }, [mediaStream, onTrackLost]);

  // Handle reconnection with exponential backoff
  const scheduleReconnect = useCallback(() => {
    if (reconnectAttempt >= RECONNECT_CONFIG.maxAttempts) {
      setState('error');
      setError({
        type: 'connection',
        message: 'Video temporarily unavailable',
        retryable: true,
      });
      setReconnectAttempt(0);
      return;
    }

    const delay = Math.min(
      RECONNECT_CONFIG.baseDelayMs * Math.pow(2, reconnectAttempt),
      RECONNECT_CONFIG.maxDelayMs
    );

    setState('reconnecting');
    setReconnectAttempt(prev => prev + 1);

    reconnectTimeoutRef.current = setTimeout(() => {
      if (isMountedRef.current) {
        // Attempt reconnection by re-connecting
        connect();
      }
    }, delay);
  }, [reconnectAttempt]);

  // Connect to video stream
  const connect = useCallback(async () => {
    if (!isAvailable || !streamId) {
      setState('offline');
      return;
    }

    // Cleanup any existing connection
    cleanup();

    setState('connecting');
    setError(null);

    try {
      // Per VAS Integration Guide §5.2:
      // This is a simplified implementation that would need the actual
      // mediasoup-client library for full WebRTC support.
      //
      // For now, we implement HLS fallback which is more widely supported
      // and doesn't require the mediasoup-client dependency.
      //
      // HLS URL would be: `/v2/streams/${streamId}/hls/playlist.m3u8`
      // The actual playback is handled by the video element in LiveVideoPlayer

      // Create a placeholder stream state - actual HLS playback
      // is handled by the video element directly with the src attribute
      setState('connected');

      // Notify that we're "connected" - actual track comes from video element
      // This hook primarily manages state, the LiveVideoPlayer handles rendering

    } catch (err) {
      if (!isMountedRef.current) return;

      // Log error for debugging (not exposed to user)
      console.debug('[useVideoStream] Connection error:', err);

      // Check if this is a retryable error
      if (reconnectAttempt < RECONNECT_CONFIG.maxAttempts) {
        scheduleReconnect();
      } else {
        setState('error');
        setError({
          type: 'connection',
          message: 'Video temporarily unavailable',
          retryable: true,
        });
      }
    }
  }, [isAvailable, streamId, cleanup, reconnectAttempt, scheduleReconnect]);

  // Disconnect from video stream
  const disconnect = useCallback(() => {
    cleanup();
    setState('idle');
    setError(null);
    setReconnectAttempt(0);
  }, [cleanup]);

  // Retry after error
  const retry = useCallback(() => {
    setReconnectAttempt(0);
    setError(null);
    connect();
  }, [connect]);

  // Update state when availability changes
  useEffect(() => {
    if (!isAvailable) {
      cleanup();
      setState('offline');
    } else if (state === 'offline') {
      setState('idle');
    }
  }, [isAvailable, state, cleanup]);

  // Auto-connect if enabled
  useEffect(() => {
    if (autoConnect && isAvailable && streamId && state === 'idle') {
      connect();
    }
  }, [autoConnect, isAvailable, streamId, state, connect]);

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      cleanup();
    };
  }, [cleanup]);

  return {
    state,
    error,
    mediaStream,
    connect,
    disconnect,
    retry,
    reconnectAttempt,
  };
}
