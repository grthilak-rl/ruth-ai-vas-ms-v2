/**
 * API Response Types
 *
 * F6-aligned types with explicit null handling.
 * NO any types. NO runtime casting without validation.
 *
 * Per F6 §9.1: Nullable fields MUST be typed as nullable.
 * Per F6 §9.2: Optional fields MUST be optional.
 * Per F6 §7: NO assumptions about data presence.
 */

// ============================================================================
// Common Types
// ============================================================================

/** ISO 8601 timestamp string */
export type ISOTimestamp = string;

/** UUID string */
export type UUID = string;

// ============================================================================
// Health Domain (F6 §4)
// ============================================================================

/**
 * System health status (F6 §4.1)
 *
 * | Status    | Meaning                                     |
 * |-----------|---------------------------------------------|
 * | healthy   | All components operational                  |
 * | degraded  | Some components unhealthy but core working  |
 * | unhealthy | Critical components down                    |
 */
export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy';

/**
 * Component health status
 */
export type ComponentHealthStatus = 'healthy' | 'degraded' | 'unhealthy';

/**
 * Database health details
 */
export interface DatabaseHealthDetails {
  /** Configured connection pool size */
  pool_size?: number;
  /** Connections currently in use */
  pool_checkedout?: number;
  /** Overflow connections in use */
  pool_overflow?: number;
  /** Connections available in pool */
  pool_checkedin?: number;
}

/**
 * Redis health details
 */
export interface RedisHealthDetails {
  /** Human-readable memory usage (e.g., "1.2MB") */
  used_memory_human?: string;
  /** Number of connected clients */
  connected_clients?: number;
  /** Server uptime in seconds */
  uptime_in_seconds?: number;
  /** Redis server version */
  redis_version?: string;
}

/**
 * AI Runtime health details
 */
export interface AIRuntimeHealthDetails {
  /** Runtime instance identifier */
  runtime_id?: string;
  /** List of loaded model IDs */
  models_loaded?: string[];
  /** Whether GPU acceleration is available */
  gpu_available?: boolean;
  /** Hardware type (cpu, gpu, jetson) */
  hardware_type?: string;
}

/**
 * VAS (Video Analytics Service) health details
 */
export interface VASHealthDetails {
  /** VAS service version */
  version?: string;
  /** VAS service name */
  service?: string;
}

/**
 * NLP Chat Service health details
 */
export interface NLPChatHealthDetails {
  /** NLP Chat Service version */
  version?: string;
  /** NLP Chat Service name */
  service?: string;
  /** Whether the chat service is enabled */
  enabled?: boolean;
  /** Ollama LLM status */
  ollama_status?: string;
  /** Available LLM models */
  models_available?: string[];
}

/**
 * Extended component health with latency and details
 */
export interface ComponentHealth {
  /** Component health status */
  status: ComponentHealthStatus;
  /** Health check latency in milliseconds */
  latency_ms?: number | null;
  /** Error message if unhealthy or degraded */
  error?: string | null;
  /** Component-specific details */
  details?: DatabaseHealthDetails | RedisHealthDetails | AIRuntimeHealthDetails | VASHealthDetails | NLPChatHealthDetails | null;
}

/**
 * Health components breakdown (F6 §4.1)
 *
 * Note: All fields are OPTIONAL - backend may not report all components.
 */
export interface HealthComponents {
  database?: ComponentHealth;
  redis?: ComponentHealth;
  ai_runtime?: ComponentHealth;
  vas?: ComponentHealth;
  nlp_chat?: ComponentHealth;
}

/**
 * System health response (F6 §4.1)
 *
 * Source: GET /api/v1/health
 */
export interface HealthResponse {
  /** Overall system status */
  status: HealthStatus;

  /** Service name (Admin display only) */
  service: string;

  /** Service version (Admin display only) */
  version: string;

  /** When health was checked */
  timestamp?: ISOTimestamp;

  /** Per-component health - MAY be absent */
  components?: HealthComponents;

  /** Service uptime in seconds */
  uptime_seconds?: number | null;

  /** Error message if unhealthy - MAY be null */
  error?: string | null;
}

// ============================================================================
// Violations Domain (F6 §3)
// ============================================================================

/**
 * Violation type (extensible)
 */
export type ViolationType = 'fall_detected' | string;

/**
 * Violation status (F6 §3.3)
 *
 * | Status     | Meaning                    |
 * |------------|----------------------------|
 * | open       | New, unseen                |
 * | reviewed   | Operator has seen          |
 * | dismissed  | Marked as false positive   |
 * | resolved   | Incident handled (terminal)|
 */
export type ViolationStatus = 'open' | 'reviewed' | 'dismissed' | 'resolved';

/**
 * Evidence status (F6 §3.4)
 *
 * | Status     | Frontend Behavior                           |
 * |------------|---------------------------------------------|
 * | pending    | Show "Preparing..." placeholder             |
 * | processing | Show "Preparing..." with progress hint      |
 * | ready      | Enable playback; show media                 |
 * | failed     | Show "Unavailable" message; hide play button|
 */
export type EvidenceStatus = 'pending' | 'processing' | 'ready' | 'failed';

/**
 * Evidence sub-object (F6 §3.1)
 *
 * ALL URL fields MAY be null.
 * HARD RULE: Frontend MUST NOT attempt to fetch evidence when status is not 'ready'.
 */
export interface ViolationEvidence {
  /** VAS snapshot reference - MAY be null */
  snapshot_id: string | null;

  /** Proxied URL - only valid if snapshot_status = "ready" */
  snapshot_url: string | null;

  /** Snapshot processing status */
  snapshot_status: EvidenceStatus;

  /** VAS bookmark reference - MAY be null */
  bookmark_id: string | null;

  /** Proxied URL - only valid if bookmark_status = "ready" */
  bookmark_url: string | null;

  /** Bookmark processing status */
  bookmark_status: EvidenceStatus;

  /** Duration of video clip - MAY be absent */
  bookmark_duration_seconds?: number;
}

/**
 * Violation entity (F6 §3.1)
 *
 * Source: GET /api/v1/violations, GET /api/v1/violations/{id}
 */
export interface Violation {
  /** Unique identifier - treat as opaque UUID */
  id: UUID;

  /** Detection type */
  type: ViolationType;

  /** Reference to device - camera MAY be deleted */
  camera_id: UUID;

  /** Human-readable camera name - denormalized for display */
  camera_name: string;

  /** Current violation status */
  status: ViolationStatus;

  /**
   * Confidence score 0.0-1.0
   *
   * HARD RULE: Frontend MUST NOT display as raw number.
   * MUST convert to categorical: High (>=0.8), Medium (0.6-0.79), Low (<0.6)
   */
  confidence: number;

  /** When detection occurred */
  timestamp: ISOTimestamp;

  /**
   * Evidence availability - MAY be absent in list responses.
   * When absent, frontend should provide default pending evidence.
   */
  evidence?: ViolationEvidence;

  /** Email of reviewer - null if not reviewed */
  reviewed_by: string | null;

  /** When reviewed - null if not reviewed */
  reviewed_at: ISOTimestamp | null;

  /** Record creation time */
  created_at: ISOTimestamp;

  /** Last modification time */
  updated_at: ISOTimestamp;
}

/**
 * Violations list response
 *
 * Source: GET /api/v1/violations
 *
 * HARD RULE (F6 §7.1): Frontend MUST NOT assume violations are returned in
 * timestamp order. Always use sort_by parameter.
 */
export interface ViolationsListResponse {
  items: Violation[];

  /** Total count - MAY change during pagination */
  total: number;

  /** Current page - MAY be absent */
  page?: number;

  /** Items per page - MAY be absent */
  limit?: number;
}

// ============================================================================
// Devices Domain (F6 §4.4)
// ============================================================================

/**
 * Stream state
 *
 * Note: Backend may return UPPERCASE or lowercase.
 * Handle both: 'live' | 'stopped' | 'LIVE' | 'STOPPED'
 */
export type StreamState = 'live' | 'stopped' | 'LIVE' | 'STOPPED' | string;

/**
 * Device streaming status (F6 §4.4)
 */
export interface DeviceStreaming {
  /** Whether stream is running */
  active: boolean;

  /** VAS stream ID - null if not streaming */
  stream_id: string | null;

  /** Stream state - MAY be null */
  state: StreamState | null;

  /** Whether AI inference is enabled */
  ai_enabled: boolean;

  /** Which model is processing - MAY be null */
  model_id: string | null;

  /** Model configuration - MAY be null */
  model_config: Record<string, unknown> | null;
}

/**
 * Device/Camera entity (F6 §4.4)
 *
 * Source: GET /api/v1/devices, GET /api/v1/devices/{id}
 */
export interface Device {
  /** VAS device ID - treat as opaque UUID */
  id: UUID;

  /** Human-readable camera name */
  name: string;

  /** Whether camera is registered as active */
  is_active: boolean;

  /** Streaming and inference status */
  streaming: DeviceStreaming;
}

/**
 * Devices list response
 *
 * Source: GET /api/v1/devices
 */
export interface DevicesListResponse {
  items: Device[];
  total: number;
}

// ============================================================================
// Models Domain (F6 §4.3)
// ============================================================================

/**
 * Model operational status
 */
export type ModelStatus = 'active' | 'idle' | 'starting' | 'stopping' | 'error';

/**
 * Model health status
 */
export type ModelHealth = 'healthy' | 'degraded' | 'unhealthy';

/**
 * Model status info (F6 §4.3)
 *
 * Source: GET /api/v1/models/status
 *
 * HARD RULE: Operators MUST NOT see model_id as raw string.
 * Display as "Detection" or "AI Detection".
 */
export interface ModelStatusInfo {
  /** Machine identifier (e.g., 'fall_detection') - Admin only */
  model_id: string;

  /** Semver version - Admin display only */
  version: string;

  /** Operational status */
  status: ModelStatus;

  /** Health status */
  health: ModelHealth;

  /** Count of cameras using this model */
  cameras_active: number;

  /** Last inference timestamp - MAY be null if never run */
  last_inference_at: ISOTimestamp | null;

  /** When model started - MAY be null if not started */
  started_at: ISOTimestamp | null;
}

/**
 * Models status response
 *
 * Source: GET /api/v1/models/status
 */
export interface ModelsStatusResponse {
  models: ModelStatusInfo[];
}

// ============================================================================
// Analytics Domain (F6 §6)
// ============================================================================

/**
 * Analytics totals (F6 §6.1)
 *
 * HARD RULE (F6 §6.2): Frontend MUST NOT perform arithmetic on counts
 * from different API calls.
 */
export interface AnalyticsTotals {
  violations_total: number;
  violations_open: number;
  violations_reviewed: number;
  violations_dismissed: number;
  violations_resolved: number;
  cameras_active: number;
}

/**
 * Analytics summary response (F6 §6.1)
 *
 * Source: GET /api/v1/analytics/summary
 */
export interface AnalyticsSummaryResponse {
  totals: AnalyticsTotals;

  /**
   * When summary was computed
   *
   * IMPORTANT (F6 §6.3): Check staleness:
   * - < 60s: Display normally
   * - 60-300s: Display with "Last updated: X ago"
   * - > 300s: Display with "Data may be outdated" warning
   */
  generated_at: ISOTimestamp;
}

// ============================================================================
// Query Parameters
// ============================================================================

/**
 * Violations list query parameters
 *
 * Note (F6 §7.1): Always specify sort_by - never assume default order.
 */
export interface ViolationsQueryParams {
  /** Filter by status */
  status?: ViolationStatus;

  /** Filter by camera ID */
  camera_id?: UUID;

  /** Filter violations after this timestamp (ISO 8601) */
  since?: ISOTimestamp;

  /** Filter violations before this timestamp (ISO 8601) */
  until?: ISOTimestamp;

  /** Sort field - REQUIRED to avoid ordering assumptions */
  sort_by?: 'timestamp' | 'created_at' | 'updated_at';

  /** Sort direction */
  sort_order?: 'asc' | 'desc';

  /** Page number (1-indexed) */
  page?: number;

  /** Items per page */
  limit?: number;
}

// ============================================================================
// Chat Domain (NLP Chat Service)
// ============================================================================

/**
 * Chat request to NLP Chat Service
 *
 * Source: POST /api/v1/chat
 */
export interface ChatRequest {
  /** Natural language question about the data */
  question: string;

  /** Whether to include raw SQL results in response */
  include_raw_data?: boolean;
}

/**
 * Chat response from NLP Chat Service
 *
 * Source: POST /api/v1/chat
 */
export interface ChatResponse {
  /** Natural language answer to the question */
  answer: string;

  /** Original question that was asked */
  question: string;

  /** Generated SQL query (for debugging/transparency) */
  generated_sql?: string | null;

  /** Raw data from SQL query - only present if include_raw_data=true */
  raw_data?: Record<string, unknown>[] | null;

  /** Number of rows returned by the query */
  row_count: number;

  /** Time taken to execute the query in milliseconds */
  execution_time_ms: number;

  /** When the response was generated */
  timestamp: ISOTimestamp;
}

/**
 * Chat service status response
 *
 * Source: GET /api/v1/chat/status
 */
export interface ChatStatusResponse {
  /** Whether the NLP Chat Service is enabled */
  enabled: boolean;

  /** Status message */
  message?: string;
}

/**
 * Chat error response
 *
 * Returned when chat request fails
 */
export interface ChatErrorDetail {
  /** Error code */
  error: 'connection_error' | 'timeout' | 'validation_error' | 'service_disabled' | 'llm_error';

  /** Human-readable error message */
  message: string;

  /** Original question */
  question: string;

  /** Generated SQL if available (for debugging) */
  generated_sql?: string | null;
}

/**
 * Chat message for UI display
 *
 * Used internally by frontend to track conversation history
 */
export interface ChatMessage {
  /** Unique message ID */
  id: string;

  /** Message role - user or assistant */
  role: 'user' | 'assistant';

  /** Message content */
  content: string;

  /** When message was created */
  timestamp: ISOTimestamp;

  /** Whether message is currently loading (for assistant messages) */
  isLoading?: boolean;

  /** Error information if request failed */
  error?: ChatErrorDetail | null;

  /** Generated SQL for transparency (assistant messages only) */
  generatedSql?: string | null;

  /** Execution time in ms (assistant messages only) */
  executionTimeMs?: number | null;
}
