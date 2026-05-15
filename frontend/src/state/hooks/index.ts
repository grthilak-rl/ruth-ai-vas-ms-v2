/**
 * Query Hooks - F6-compliant polling and data access
 *
 * These hooks use the centralized API module for all network access.
 * For API functions and types, import from '../api' or from the main state module.
 */

export {
  useHealthQuery,
  deriveGlobalStatus,
  getGlobalStatusDisplay,
  type GlobalStatus,
} from './useHealthQuery';

export {
  useViolationsQuery,
  useAlertsBadgeQuery,
  useViolationQuery,
  useUpdateViolationMutation,
  useAcknowledgeViolation,
  useDismissViolation,
  getConfidenceCategory,
  getConfidenceDisplay,
} from './useViolationsQuery';

export {
  useDevicesQuery,
  useDeviceQuery,
} from './useDevicesQuery';

export {
  useModelsStatusQuery,
} from './useModelsStatusQuery';

export {
  useChatStatusQuery,
  useChatMutation,
  useEnableChatMutation,
  useDisableChatMutation,
  createUserMessage,
  createAssistantMessage,
  createLoadingMessage,
  createErrorMessage,
  generateMessageId,
  formatExecutionTime,
} from './useChatMutation';

export {
  useHardwareQuery,
  deriveCapacityStatus,
  getCapacityStatusDisplay,
  type CapacityStatus,
} from './useHardwareQuery';

export {
  useBookmarkAnalysesListQuery,
  useAnalysesForBookmarkQuery,
  useBookmarkAnalysisQuery,
  useSubmitBookmarkAnalysisMutation,
  type BookmarkAnalysis,
  type BookmarkAnalysisListItem,
  type BookmarkAnalysisListResponse,
  type BookmarkAnalysisSubmitRequest,
} from './useBookmarkAnalysesQuery';

export {
  useBookmarksListQuery,
  type VasBookmark,
} from './useBookmarksQuery';
