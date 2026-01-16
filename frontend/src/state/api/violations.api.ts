/**
 * Violations API
 *
 * API for violations (F6 §3).
 *
 * Source Endpoints:
 * - GET /api/v1/violations
 * - GET /api/v1/violations/{id}
 * - PATCH /api/v1/violations/{id}
 *
 * HARD RULES:
 * - F6 §7.1: MUST NOT assume ordering - always use sort_by parameter
 * - F6 §7.2: MUST NOT assume all violations have evidence
 * - F6 §3.2: MUST NOT expose raw confidence numbers
 * - F6 §10.1: Optimistic update with rollback on failure
 */

import { apiGet, apiPatch } from './client';
import type {
  Violation,
  ViolationsListResponse,
  ViolationsQueryParams,
  EvidenceStatus,
} from './types';
import {
  isViolation,
  isViolationsListResponse,
  assertResponse,
} from './validators';

/** API path for violations */
const VIOLATIONS_PATH = '/api/v1/violations';

/**
 * Build query string from params
 *
 * F6 §7.1: Always specify sort_by to avoid ordering assumptions.
 */
function buildQueryString(params?: ViolationsQueryParams): string {
  if (!params) return '';

  const searchParams = new URLSearchParams();

  if (params.status) {
    searchParams.set('status', params.status);
  }
  if (params.camera_id) {
    searchParams.set('camera_id', params.camera_id);
  }
  if (params.since) {
    searchParams.set('since', params.since);
  }
  if (params.until) {
    searchParams.set('until', params.until);
  }
  if (params.sort_by) {
    searchParams.set('sort_by', params.sort_by);
  }
  if (params.sort_order) {
    searchParams.set('sort_order', params.sort_order);
  }
  if (params.page !== undefined) {
    searchParams.set('page', String(params.page));
  }
  if (params.limit !== undefined) {
    searchParams.set('limit', String(params.limit));
  }

  const queryString = searchParams.toString();
  return queryString ? `?${queryString}` : '';
}

/**
 * Fetch violations list
 *
 * Returns paginated list of violations.
 *
 * IMPORTANT (F6 §7.1):
 * - MUST NOT assume violations are returned in timestamp order
 * - MUST NOT assume new violations appear at list top
 * - Always use sort_by parameter
 */
export async function fetchViolations(
  params?: ViolationsQueryParams
): Promise<ViolationsListResponse> {
  const queryString = buildQueryString(params);
  const response = await apiGet<unknown>(`${VIOLATIONS_PATH}${queryString}`);
  return assertResponse(response, isViolationsListResponse, 'ViolationsListResponse');
}

/**
 * Fetch single violation detail
 *
 * Returns full violation information including evidence.
 *
 * F6 §3.4: Evidence availability must be checked via status field.
 * - MUST NOT attempt to fetch evidence when status is not 'ready'
 */
export async function fetchViolation(id: string): Promise<Violation> {
  const response = await apiGet<unknown>(`${VIOLATIONS_PATH}/${id}`);
  return assertResponse(response, isViolation, 'Violation');
}

// ============================================================================
// Violation Actions (E5)
// ============================================================================

/**
 * Update violation request payload
 *
 * Per API Contract: PATCH /api/v1/violations/{id}
 */
export interface UpdateViolationRequest {
  /** New status: reviewed, dismissed, resolved */
  status?: 'reviewed' | 'dismissed' | 'resolved';
  /** Operator notes (max 2000 chars) */
  resolution_notes?: string;
}

/**
 * Update violation response (partial)
 *
 * Returns updated fields only.
 */
export interface UpdateViolationResponse {
  id: string;
  status: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  resolution_notes: string | null;
  updated_at: string;
}

/**
 * Update violation status
 *
 * Used for:
 * - Acknowledge (status: 'reviewed')
 * - Dismiss (status: 'dismissed')
 * - Resolve (status: 'resolved')
 *
 * F6 §10.1: UI should use optimistic update with rollback on failure.
 *
 * Status Transition Rules:
 * | From       | Allowed To              |
 * |------------|-------------------------|
 * | open       | reviewed, dismissed     |
 * | reviewed   | dismissed, resolved     |
 * | dismissed  | open (re-open)          |
 * | resolved   | - (terminal)            |
 */
export async function updateViolationStatus(
  id: string,
  update: UpdateViolationRequest
): Promise<UpdateViolationResponse> {
  const response = await apiPatch<unknown>(`${VIOLATIONS_PATH}/${id}`, update);
  // Minimal validation - trust backend shape
  return response as UpdateViolationResponse;
}

// ============================================================================
// Confidence Helpers (F6 §3.2)
// ============================================================================

/**
 * Confidence category (F6 §3.2)
 *
 * HARD RULE: Frontend MUST NOT display raw confidence numbers.
 * Always use categorical labels.
 */
export type ConfidenceCategory = 'high' | 'medium' | 'low';

/**
 * Convert numeric confidence to category (F6 §3.2)
 *
 * | Backend Value | Frontend Display |
 * |---------------|------------------|
 * | >= 0.8        | "High"           |
 * | 0.6 – 0.79    | "Medium"         |
 * | < 0.6         | "Low"            |
 */
export function getConfidenceCategory(confidence: number): ConfidenceCategory {
  if (confidence >= 0.8) return 'high';
  if (confidence >= 0.6) return 'medium';
  return 'low';
}

/**
 * Get display label for confidence category
 */
export function getConfidenceLabel(confidence: number): string {
  const category = getConfidenceCategory(confidence);
  switch (category) {
    case 'high':
      return 'High';
    case 'medium':
      return 'Medium';
    case 'low':
      return 'Low';
  }
}

// ============================================================================
// Evidence Helpers (F6 §3.4)
// ============================================================================

/**
 * Check if snapshot is available for viewing
 *
 * F6 §3.4: MUST NOT attempt to fetch evidence when status is not 'ready'
 */
export function isSnapshotReady(evidence: Violation['evidence'] | undefined): boolean {
  if (!evidence) return false;
  return evidence.snapshot_status === 'ready' && evidence.snapshot_url !== null;
}

/**
 * Check if video bookmark is available for viewing
 *
 * F6 §3.4: MUST NOT attempt to fetch evidence when status is not 'ready'
 */
export function isVideoReady(evidence: Violation['evidence'] | undefined): boolean {
  if (!evidence) return false;
  return evidence.bookmark_status === 'ready' && evidence.bookmark_url !== null;
}

/**
 * Get evidence display state (F6 §3.4)
 */
export type EvidenceDisplayState = 'ready' | 'preparing' | 'unavailable';

export function getEvidenceDisplayState(
  status: EvidenceStatus | undefined
): EvidenceDisplayState {
  switch (status) {
    case 'ready':
      return 'ready';
    case 'pending':
    case 'processing':
      return 'preparing';
    case 'failed':
      return 'unavailable';
    default:
      return 'unavailable';
  }
}

// ============================================================================
// Re-exports for consumers
// ============================================================================

export type {
  Violation,
  ViolationsListResponse,
  ViolationsQueryParams,
  ViolationType,
  ViolationStatus,
  ViolationEvidence,
  EvidenceStatus,
} from './types';
