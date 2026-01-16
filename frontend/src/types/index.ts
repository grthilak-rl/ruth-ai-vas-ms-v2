// Device types (V1 API)
export interface Device {
  id: string;
  name: string;
  description?: string;
  rtsp_url: string;
  is_active: boolean;
  location?: string;
  created_at: string;
  updated_at?: string;
}

export interface StreamStartResponse {
  status: string;
  device_id: string;
  room_id?: string;
  transport_id?: string;
  producers?: {
    video?: string;
    audio?: string;
  };
  stream?: {
    status: string;
    message?: string;
    started_at: string;
  };
  v2_stream_id?: string;
  reconnect?: boolean;
}

// Stream types (V2 API)
export type StreamState = 'initializing' | 'ready' | 'live' | 'error' | 'stopped' | 'closed' |
  'INITIALIZING' | 'READY' | 'LIVE' | 'ERROR' | 'STOPPED' | 'CLOSED';

export interface Stream {
  id: string;
  name?: string;
  camera_id: string;
  state: StreamState;
  codec_config?: Record<string, unknown>;
  producer?: {
    id: string;
    mediasoup_id?: string;
    state: string;
    ssrc?: number;
  };
  consumers?: {
    count: number;
    active: number;
  };
  endpoints?: {
    webrtc?: string;
    hls?: string;
    health?: string;
  };
  created_at: string;
  uptime_seconds?: number;
}

// WebRTC Consumer types
export interface ICECandidate {
  foundation: string;
  priority: number;
  ip: string;
  port: number;
  type: string;
  protocol: string;
}

export interface ICEParameters {
  usernameFragment: string;
  password: string;
}

export interface DTLSFingerprint {
  algorithm: string;
  value: string;
}

export interface DTLSParameters {
  role: string;
  fingerprints: DTLSFingerprint[];
}

export interface Transport {
  id: string;
  ice_parameters: ICEParameters;
  ice_candidates: ICECandidate[];
  dtls_parameters: DTLSParameters;
}

export interface RTPParameters {
  codecs: Record<string, unknown>[];
  encodings: Record<string, unknown>[];
}

export interface ConsumeResponse {
  consumer_id: string;
  transport: Transport;
  rtp_parameters: RTPParameters;
}

export interface RouterCapabilitiesResponse {
  rtp_capabilities: {
    codecs: Record<string, unknown>[];
    headerExtensions: Record<string, unknown>[];
  };
}

// Token types
export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_token: string;
  scopes: string[];
}
