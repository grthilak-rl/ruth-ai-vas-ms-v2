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
  useAnalyticsQuery,
} from './useAnalyticsQuery';

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
