/**
 * State Module - Public API
 *
 * This module provides the state management layer for Ruth AI frontend.
 * All exports are documented in STATE_OWNERSHIP.md.
 *
 * IMPORTANT: All network access MUST flow through the api/ module.
 * No component or hook may call fetch() directly.
 */

// Query Client
export { queryClient } from './queryClient';

// Query Keys
export { queryKeys, type ViolationFilters } from './queryKeys';

// Polling Intervals (F6-compliant)
export { POLLING_INTERVALS } from './pollingIntervals';

// ============================================================================
// API Module - Centralized API Access (E3)
// ============================================================================

// Client & Error Handling
export {
  apiGet,
  apiGetFull,
  ApiError,
  USER_MESSAGES,
  classifyStatus,
  getUserMessageForStatus,
  isStatusRetryable,
  createNetworkError,
  ValidationError,
} from './api';

export type {
  RequestOptions,
  RequestResult,
  ApiErrorCategory,
} from './api';

// Types (F6-aligned with null safety)
export type {
  // Common
  ISOTimestamp,
  UUID,
  // Health
  HealthStatus,
  ComponentHealth,
  HealthComponents,
  HealthResponse,
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
} from './api';

// Validators
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
} from './api';

// Domain API Functions
export {
  // Health
  fetchHealth,
  fetchHealthWithFallback,
  // Violations
  fetchViolations,
  fetchViolation,
  updateViolationStatus,
  getConfidenceLabel,
  isSnapshotReady,
  isVideoReady,
  getEvidenceDisplayState,
  // Devices
  fetchDevices,
  fetchDevice,
  getCameraStatus,
  getCameraStatusLabel,
  getDetectionStatus,
  getDetectionStatusLabel,
  normalizeStreamState,
  isStreamLive,
  // Models
  fetchModelsStatus,
  getModelDisplay,
  humanizeModelId,
  isAnyModelHealthy,
  areAllModelsUnavailable,
  getOverallModelHealth,
  // Analytics
  fetchAnalyticsSummary,
  STALENESS_THRESHOLDS,
  getStalenessLevel,
  getStalenessMessage,
  formatCount,
  formatRatio,
} from './api';

export type {
  ConfidenceCategory,
  EvidenceDisplayState,
  CameraStatus,
  DetectionStatus,
  ModelDisplayInfo,
  OverallModelHealth,
  StalenessLevel,
} from './api';

// ============================================================================
// Query Hooks
// ============================================================================

export {
  // Health
  useHealthQuery,
  deriveGlobalStatus,
  getGlobalStatusDisplay,
  // Violations
  useViolationsQuery,
  useViolationQuery,
  useUpdateViolationMutation,
  useAcknowledgeViolation,
  useDismissViolation,
  getConfidenceCategory,
  getConfidenceDisplay,
  // Devices
  useDevicesQuery,
  useDeviceQuery,
  // Models
  useModelsStatusQuery,
  // Analytics
  useAnalyticsQuery,
} from './hooks';

// GlobalStatus type from health hook (derived from HealthResponse)
export type { GlobalStatus } from './hooks';

// ============================================================================
// Auth Context
// ============================================================================

export {
  AuthProvider,
  useAuth,
  useHasRole,
  useIsAdmin,
  useIsSupervisor,
  type UserRole,
} from './context/AuthContext';

// ============================================================================
// Error Handling Utilities
// ============================================================================

// Re-export from errorHandling for backward compatibility
export {
  ERROR_MESSAGES,
  getErrorMessage,
  shouldRetry,
  isAuthError,
  isPermissionError,
  isNotFoundError,
  getRetryConfig,
  deriveDegradationState,
  type RetryConfig,
  type DegradationState,
  type QueryStatus,
} from './errorHandling';
