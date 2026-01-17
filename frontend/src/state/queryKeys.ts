/**
 * Query Keys
 *
 * Standardized query keys for cache management.
 * All query keys are typed for type safety.
 */

import type { ViolationStatus } from './api/types';

/**
 * Violation query filters (F6-aligned with ViolationsQueryParams)
 */
export interface ViolationFilters {
  /** Filter by status */
  status?: ViolationStatus;

  /** Filter by camera ID */
  camera_id?: string;

  /** Filter violations after this timestamp (ISO 8601) */
  since?: string;

  /** Filter violations before this timestamp (ISO 8601) */
  until?: string;

  /** Sort field - REQUIRED to avoid ordering assumptions (F6 §7.1) */
  sort_by?: 'timestamp' | 'created_at' | 'updated_at';

  /** Sort direction */
  sort_order?: 'asc' | 'desc';

  /** Page number (1-indexed) */
  page?: number;

  /** Items per page */
  limit?: number;
}

export const queryKeys = {
  // Health domain
  health: ['health'] as const,

  // Violations domain
  violations: {
    all: ['violations'] as const,
    list: (filters?: ViolationFilters) =>
      filters
        ? (['violations', 'list', filters] as const)
        : (['violations', 'list'] as const),
    detail: (id: string) => ['violations', 'detail', id] as const,
  },

  // Devices domain
  devices: {
    all: ['devices'] as const,
    list: () => ['devices', 'list'] as const,
    detail: (id: string) => ['devices', 'detail', id] as const,
  },

  // Models domain
  models: {
    status: ['models', 'status'] as const,
  },

  // Analytics domain
  analytics: {
    summary: ['analytics', 'summary'] as const,
  },

  // Chat domain (NLP Chat Service)
  chat: {
    status: ['chat', 'status'] as const,
  },

  // Hardware domain
  hardware: ['hardware'] as const,
} as const;
