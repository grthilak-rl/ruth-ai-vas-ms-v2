/**
 * Response Validators
 *
 * Type guards and sanity checks for API responses.
 * NO runtime casting without validation.
 *
 * These validators ensure responses match expected shapes
 * and surface unexpected data explicitly (not hidden).
 */

import type {
  HealthResponse,
  HealthStatus,
  Violation,
  ViolationsListResponse,
  ViolationEvidence,
  EvidenceStatus,
  ViolationStatus,
  Device,
  DevicesListResponse,
  DeviceStreaming,
  ModelStatusInfo,
  ModelsStatusResponse,
  ModelStatus,
  ModelHealth,
  AnalyticsSummaryResponse,
} from './types';

// ============================================================================
// Basic Type Guards
// ============================================================================

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && !isNaN(value);
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === 'boolean';
}

function isArray(value: unknown): value is unknown[] {
  return Array.isArray(value);
}

function isStringOrNull(value: unknown): value is string | null {
  return value === null || isString(value);
}

function isNumberOrNullOrUndefined(value: unknown): value is number | null | undefined {
  return value === undefined || value === null || isNumber(value);
}

// ============================================================================
// Enum Guards
// ============================================================================

const HEALTH_STATUSES: HealthStatus[] = ['healthy', 'unhealthy'];
function isHealthStatus(value: unknown): value is HealthStatus {
  return isString(value) && HEALTH_STATUSES.includes(value as HealthStatus);
}

const EVIDENCE_STATUSES: EvidenceStatus[] = ['pending', 'processing', 'ready', 'failed'];
function isEvidenceStatus(value: unknown): value is EvidenceStatus {
  return isString(value) && EVIDENCE_STATUSES.includes(value as EvidenceStatus);
}

const VIOLATION_STATUSES: ViolationStatus[] = ['open', 'reviewed', 'dismissed', 'resolved'];
function isViolationStatus(value: unknown): value is ViolationStatus {
  return isString(value) && VIOLATION_STATUSES.includes(value as ViolationStatus);
}

const MODEL_STATUSES: ModelStatus[] = ['active', 'idle', 'starting', 'stopping', 'error'];
function isModelStatus(value: unknown): value is ModelStatus {
  return isString(value) && MODEL_STATUSES.includes(value as ModelStatus);
}

const MODEL_HEALTHS: ModelHealth[] = ['healthy', 'degraded', 'unhealthy'];
function isModelHealth(value: unknown): value is ModelHealth {
  return isString(value) && MODEL_HEALTHS.includes(value as ModelHealth);
}

// ============================================================================
// Domain Validators
// ============================================================================

/**
 * Validate HealthResponse
 */
export function isHealthResponse(value: unknown): value is HealthResponse {
  if (!isObject(value)) return false;

  const { status, service, version } = value;

  return (
    isHealthStatus(status) &&
    isString(service) &&
    isString(version)
  );
}

/**
 * Validate ViolationEvidence
 */
export function isViolationEvidence(value: unknown): value is ViolationEvidence {
  if (!isObject(value)) return false;

  const {
    snapshot_id,
    snapshot_url,
    snapshot_status,
    bookmark_id,
    bookmark_url,
    bookmark_status,
    bookmark_duration_seconds,
  } = value;

  return (
    isStringOrNull(snapshot_id) &&
    isStringOrNull(snapshot_url) &&
    isEvidenceStatus(snapshot_status) &&
    isStringOrNull(bookmark_id) &&
    isStringOrNull(bookmark_url) &&
    isEvidenceStatus(bookmark_status) &&
    isNumberOrNullOrUndefined(bookmark_duration_seconds)
  );
}

/**
 * Validate Violation
 *
 * Note: evidence field may be missing from list responses.
 * When missing, we provide a default "pending" evidence object.
 *
 * For detail responses, evidence may be an array of EvidenceResponse objects.
 * We accept both formats.
 */
export function isViolation(value: unknown): value is Violation {
  if (!isObject(value)) return false;

  const {
    id,
    type,
    camera_id,
    camera_name,
    status,
    confidence,
    timestamp,
    evidence,
    reviewed_by,
    reviewed_at,
    created_at,
    updated_at,
  } = value;

  // Core fields must be present
  const coreFieldsValid =
    isString(id) &&
    isString(type) &&
    isString(camera_id) &&
    isString(camera_name) &&
    isViolationStatus(status) &&
    isNumber(confidence) &&
    isString(timestamp) &&
    isStringOrNull(reviewed_by) &&
    isStringOrNull(reviewed_at) &&
    isString(created_at) &&
    isString(updated_at);

  if (!coreFieldsValid) return false;

  // Evidence can be:
  // 1. undefined/null (missing)
  // 2. ViolationEvidence object (summary from list response)
  // 3. Array of EvidenceResponse objects (detail response)
  if (evidence !== undefined && evidence !== null) {
    // Accept array (detail response) or object (summary)
    if (!isArray(evidence) && !isViolationEvidence(evidence)) {
      return false;
    }
  }

  return true;
}

/**
 * Validate ViolationsListResponse
 *
 * Note: page and limit are optional - backend may omit them
 */
export function isViolationsListResponse(value: unknown): value is ViolationsListResponse {
  if (!isObject(value)) return false;

  const { items, total, page, limit } = value;

  if (!isArray(items)) return false;
  if (!isNumber(total)) return false;
  // page and limit are optional (backend may not return them)
  if (page !== undefined && !isNumber(page)) return false;
  if (limit !== undefined && !isNumber(limit)) return false;

  // Validate each item
  return items.every(isViolation);
}

/**
 * Validate DeviceStreaming
 */
export function isDeviceStreaming(value: unknown): value is DeviceStreaming {
  if (!isObject(value)) return false;

  const { active, stream_id, state, ai_enabled, model_id } = value;

  return (
    isBoolean(active) &&
    isStringOrNull(stream_id) &&
    (state === null || isString(state)) &&
    isBoolean(ai_enabled) &&
    isStringOrNull(model_id)
  );
}

/**
 * Validate Device
 */
export function isDevice(value: unknown): value is Device {
  if (!isObject(value)) return false;

  const { id, name, is_active, streaming } = value;

  return (
    isString(id) &&
    isString(name) &&
    isBoolean(is_active) &&
    isDeviceStreaming(streaming)
  );
}

/**
 * Validate DevicesListResponse
 */
export function isDevicesListResponse(value: unknown): value is DevicesListResponse {
  if (!isObject(value)) return false;

  const { items, total } = value;

  if (!isArray(items)) return false;
  if (!isNumber(total)) return false;

  return items.every(isDevice);
}

/**
 * Validate ModelStatusInfo
 */
export function isModelStatusInfo(value: unknown): value is ModelStatusInfo {
  if (!isObject(value)) return false;

  const {
    model_id,
    version,
    status,
    health,
    cameras_active,
    last_inference_at,
    started_at,
  } = value;

  return (
    isString(model_id) &&
    isString(version) &&
    isModelStatus(status) &&
    isModelHealth(health) &&
    isNumber(cameras_active) &&
    isStringOrNull(last_inference_at) &&
    isStringOrNull(started_at)
  );
}

/**
 * Validate ModelsStatusResponse
 */
export function isModelsStatusResponse(value: unknown): value is ModelsStatusResponse {
  if (!isObject(value)) return false;

  const { models } = value;

  if (!isArray(models)) return false;

  return models.every(isModelStatusInfo);
}

/**
 * Validate AnalyticsSummaryResponse
 */
export function isAnalyticsSummaryResponse(value: unknown): value is AnalyticsSummaryResponse {
  if (!isObject(value)) return false;

  const { totals, generated_at } = value;

  if (!isObject(totals)) return false;
  if (!isString(generated_at)) return false;

  const {
    violations_total,
    violations_open,
    violations_reviewed,
    violations_dismissed,
    violations_resolved,
    cameras_active,
  } = totals;

  return (
    isNumber(violations_total) &&
    isNumber(violations_open) &&
    isNumber(violations_reviewed) &&
    isNumber(violations_dismissed) &&
    isNumber(violations_resolved) &&
    isNumber(cameras_active)
  );
}

// ============================================================================
// Validation Utilities
// ============================================================================

/**
 * Validation error with details
 */
export class ValidationError extends Error {
  readonly expectedType: string;
  readonly receivedValue: unknown;

  constructor(expectedType: string, receivedValue: unknown) {
    super(`Expected ${expectedType}, received: ${JSON.stringify(receivedValue)}`);
    this.name = 'ValidationError';
    this.expectedType = expectedType;
    this.receivedValue = receivedValue;
  }
}

/**
 * Assert response matches expected type
 *
 * Use this to validate API responses before returning to callers.
 * Throws ValidationError with details if validation fails.
 */
export function assertResponse<T>(
  value: unknown,
  validator: (v: unknown) => v is T,
  typeName: string
): T {
  if (validator(value)) {
    return value;
  }

  throw new ValidationError(typeName, value);
}

/**
 * Safe validation that returns undefined instead of throwing
 *
 * Use when you want to handle invalid data gracefully.
 */
export function validateSafe<T>(
  value: unknown,
  validator: (v: unknown) => v is T
): T | undefined {
  return validator(value) ? value : undefined;
}
