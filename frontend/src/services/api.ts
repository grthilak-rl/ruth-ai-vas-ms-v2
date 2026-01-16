import type {
  Device,
  StreamStartResponse,
  Stream,
  RouterCapabilitiesResponse,
  ConsumeResponse,
  TokenResponse,
} from '../types';

// Configuration
const VAS_DEFAULT_CLIENT_ID = 'vas-portal';
const VAS_DEFAULT_CLIENT_SECRET = 'vas-portal-secret-2024';

// Token management (simple in-memory store for this minimal implementation)
let accessToken: string | null = null;
let tokenExpiresAt: number = 0;

/**
 * Get or refresh access token
 */
async function ensureAccessToken(): Promise<string> {
  // Check if we have a valid token
  if (accessToken && Date.now() < tokenExpiresAt - 60000) {
    return accessToken;
  }

  // Get new token
  const response = await fetch('/v2/auth/token', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      client_id: VAS_DEFAULT_CLIENT_ID,
      client_secret: VAS_DEFAULT_CLIENT_SECRET,
    }),
  });

  if (!response.ok) {
    throw new Error(`Failed to get access token: ${response.status}`);
  }

  const data: TokenResponse = await response.json();
  accessToken = data.access_token;
  tokenExpiresAt = Date.now() + data.expires_in * 1000;

  console.log('[API] Obtained new access token');
  return accessToken;
}

/**
 * Make authenticated request to V2 API
 */
async function authenticatedFetch(
  url: string,
  options: RequestInit = {}
): Promise<Response> {
  const token = await ensureAccessToken();

  const headers = new Headers(options.headers);
  headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  return fetch(url, {
    ...options,
    headers,
  });
}

// ============================================================================
// Device APIs (V1 - No authentication required)
// ============================================================================

/**
 * List all devices
 */
export async function listDevices(): Promise<Device[]> {
  const response = await fetch('/api/v1/devices');

  if (!response.ok) {
    throw new Error(`Failed to list devices: ${response.status}`);
  }

  return response.json();
}

/**
 * Get device status
 */
export async function getDeviceStatus(deviceId: string): Promise<{
  device_id: string;
  name: string;
  is_active: boolean;
  streaming: {
    active: boolean;
    room_id?: string;
    started_at?: string;
  };
}> {
  const response = await fetch(`/api/v1/devices/${deviceId}/status`);

  if (!response.ok) {
    throw new Error(`Failed to get device status: ${response.status}`);
  }

  return response.json();
}

/**
 * Start streaming from a device
 */
export async function startStream(deviceId: string): Promise<StreamStartResponse> {
  const response = await fetch(`/api/v1/devices/${deviceId}/start-stream`, {
    method: 'POST',
  });

  if (!response.ok) {
    throw new Error(`Failed to start stream: ${response.status}`);
  }

  return response.json();
}

/**
 * Stop streaming from a device
 */
export async function stopStream(deviceId: string): Promise<void> {
  const response = await fetch(`/api/v1/devices/${deviceId}/stop-stream`, {
    method: 'POST',
  });

  if (!response.ok) {
    throw new Error(`Failed to stop stream: ${response.status}`);
  }
}

// ============================================================================
// Stream APIs (V2 - Authentication required)
// ============================================================================

/**
 * Get stream details
 */
export async function getStream(streamId: string): Promise<Stream> {
  const response = await authenticatedFetch(`/v2/streams/${streamId}`);

  if (!response.ok) {
    throw new Error(`Failed to get stream: ${response.status}`);
  }

  return response.json();
}

/**
 * Get router RTP capabilities (required for mediasoup-client Device initialization)
 */
export async function getRouterCapabilities(
  streamId: string
): Promise<RouterCapabilitiesResponse> {
  const response = await authenticatedFetch(
    `/v2/streams/${streamId}/router-capabilities`
  );

  if (!response.ok) {
    throw new Error(`Failed to get router capabilities: ${response.status}`);
  }

  return response.json();
}

/**
 * Attach a WebRTC consumer to a stream
 */
export async function attachConsumer(
  streamId: string,
  clientId: string,
  rtpCapabilities: Record<string, unknown>
): Promise<ConsumeResponse> {
  const response = await authenticatedFetch(`/v2/streams/${streamId}/consume`, {
    method: 'POST',
    body: JSON.stringify({
      client_id: clientId,
      rtp_capabilities: rtpCapabilities,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to attach consumer: ${response.status} - ${errorText}`);
  }

  return response.json();
}

/**
 * Connect consumer transport (DTLS handshake)
 */
export async function connectConsumer(
  streamId: string,
  consumerId: string,
  dtlsParameters: Record<string, unknown>
): Promise<void> {
  const response = await authenticatedFetch(
    `/v2/streams/${streamId}/consumers/${consumerId}/connect`,
    {
      method: 'POST',
      body: JSON.stringify({
        dtls_parameters: dtlsParameters,
      }),
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to connect consumer: ${response.status}`);
  }
}

/**
 * Detach and close a consumer
 */
export async function detachConsumer(
  streamId: string,
  consumerId: string
): Promise<void> {
  const response = await authenticatedFetch(
    `/v2/streams/${streamId}/consumers/${consumerId}`,
    {
      method: 'DELETE',
    }
  );

  if (!response.ok && response.status !== 404) {
    throw new Error(`Failed to detach consumer: ${response.status}`);
  }
}

// ============================================================================
// Event/Violation APIs (Internal - for fall detection reporting)
// ============================================================================

export interface BoundingBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface EventIngestRequest {
  device_id: string;
  stream_session_id?: string;
  vas_stream_id?: string;  // VAS stream ID for snapshot capture
  event_type: string;
  confidence: number;
  timestamp: string;
  model_id: string;
  model_version: string;
  bounding_boxes?: BoundingBox[];
}

export interface EventResponse {
  id: string;
  device_id: string;
  event_type: string;
  confidence: number;
  timestamp: string;
  model_id: string;
  model_version: string;
  bounding_boxes?: Array<{ x: number; y: number; width: number; height: number }>;
  violation_id?: string;
  created_at: string;
}

/**
 * Report a fall detection event to the backend
 * This creates an Event and optionally a Violation if event_type is "fall_detected"
 * If vasStreamId is provided, the backend will attempt to capture a snapshot via VAS
 */
export async function reportFallEvent(
  deviceId: string,
  confidence: number,
  boundingBoxes?: BoundingBox[],
  vasStreamId?: string,
  modelId: string = 'fall-detection-yolov8',
  modelVersion: string = '1.0.0'
): Promise<EventResponse> {
  const payload: EventIngestRequest = {
    device_id: deviceId,
    event_type: 'fall_detected',
    confidence,
    timestamp: new Date().toISOString(),
    model_id: modelId,
    model_version: modelVersion,
    bounding_boxes: boundingBoxes,
  };

  // Only include vas_stream_id if it has a value
  if (vasStreamId) {
    payload.vas_stream_id = vasStreamId;
  }

  const response = await fetch('/internal/events', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to report fall event: ${response.status} - ${errorText}`);
  }

  return response.json();
}

/**
 * Wait for stream to become LIVE
 */
export async function waitForStreamLive(
  streamId: string,
  maxWaitMs: number = 30000,
  pollIntervalMs: number = 1000
): Promise<Stream> {
  const startTime = Date.now();

  while (Date.now() - startTime < maxWaitMs) {
    const stream = await getStream(streamId);
    const state = stream.state.toLowerCase();

    if (state === 'live') {
      return stream;
    }

    if (state === 'error' || state === 'stopped' || state === 'closed') {
      throw new Error(`Stream entered terminal state: ${state}`);
    }

    // Wait before next poll
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }

  throw new Error('Timeout waiting for stream to become LIVE');
}
