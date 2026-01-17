/**
 * API Module - Public API
 *
 * This module is the ONLY allowed way the frontend talks to the backend.
 * No component or hook may call fetch() directly.
 *
 * All exports are read-only for E3. Write operations will be added later.
 */

// ============================================================================
// Client & Error Handling
// ============================================================================

export { apiGet, apiGetFull, apiPatch, apiPost, ApiError } from './client';
export type { RequestOptions, RequestResult, ApiErrorCategory } from './client';

export {
  USER_MESSAGES,
  classifyStatus,
  getUserMessageForStatus,
  isStatusRetryable,
  createNetworkError,
} from './errors';

// ============================================================================
// Types
// ============================================================================

export type {
  // Common
  ISOTimestamp,
  UUID,

  // Health
  HealthStatus,
  ComponentHealthStatus,
  ComponentHealth,
  HealthComponents,
  HealthResponse,
  DatabaseHealthDetails,
  RedisHealthDetails,
  AIRuntimeHealthDetails,
  VASHealthDetails,
  NLPChatHealthDetails,

  // Violations
  ViolationType,
  ViolationStatus,
  EvidenceStatus,
  ViolationEvidence,
  Violation,
  ViolationsListResponse,
  ViolationsQueryParams,

  // Devices
  StreamState,
  DeviceStreaming,
  Device,
  DevicesListResponse,

  // Models
  ModelStatus,
  ModelHealth,
  ModelStatusInfo,
  ModelsStatusResponse,

  // Analytics
  AnalyticsTotals,
  AnalyticsSummaryResponse,
} from './types';

// ============================================================================
// Validators
// ============================================================================

export {
  isHealthResponse,
  isViolation,
  isViolationsListResponse,
  isDevice,
  isDevicesListResponse,
  isModelStatusInfo,
  isModelsStatusResponse,
  isAnalyticsSummaryResponse,
  assertResponse,
  validateSafe,
  ValidationError,
} from './validators';

// ============================================================================
// Health API
// ============================================================================

export {
  fetchHealth,
  fetchHealthWithFallback,
  formatUptime,
  getTimeSinceLastCheck,
  getComponentDisplayName,
} from './health.api';

// ============================================================================
// Violations API
// ============================================================================

export {
  fetchViolations,
  fetchViolation,
  updateViolationStatus,
  getConfidenceCategory,
  getConfidenceLabel,
  isSnapshotReady,
  isVideoReady,
  getEvidenceDisplayState,
} from './violations.api';
export type {
  ConfidenceCategory,
  EvidenceDisplayState,
  UpdateViolationRequest,
  UpdateViolationResponse,
} from './violations.api';

// ============================================================================
// Devices API
// ============================================================================

export {
  fetchDevices,
  fetchDevice,
  getCameraStatus,
  getCameraStatusLabel,
  getDetectionStatus,
  getDetectionStatusLabel,
  normalizeStreamState,
  isStreamLive,
} from './devices.api';
export type { CameraStatus, DetectionStatus } from './devices.api';

// ============================================================================
// Models API
// ============================================================================

export {
  fetchModelsStatus,
  getModelDisplay,
  humanizeModelId,
  isAnyModelHealthy,
  areAllModelsUnavailable,
  getOverallModelHealth,
} from './models.api';
export type { ModelDisplayInfo, OverallModelHealth } from './models.api';

// ============================================================================
// Analytics API
// ============================================================================

export {
  fetchAnalyticsSummary,
  STALENESS_THRESHOLDS,
  getStalenessLevel,
  getStalenessMessage,
  formatCount,
  formatRatio,
} from './analytics.api';
export type { StalenessLevel } from './analytics.api';

// ============================================================================
// Chat API (NLP Chat Service)
// ============================================================================

export {
  sendChatMessage,
  getChatStatus,
  enableChatService,
  disableChatService,
  generateMessageId,
  formatExecutionTime,
} from './chat.api';
export type {
  ChatRequest,
  ChatResponse,
  ChatStatusResponse,
  ChatErrorDetail,
  ChatMessage,
} from './types';

// ============================================================================
// Hardware API
// ============================================================================

export {
  fetchHardware,
  getUsageLevel,
  formatGB,
  formatPercent,
  getTimeSinceUpdate,
} from './hardware.api';
export type {
  HardwareResponse,
  GPUMetrics,
  CPUMetrics,
  RAMMetrics,
  ModelServiceStatus,
  ModelsMetrics,
  CapacityMetrics,
  UsageLevel,
} from './hardware.api';
