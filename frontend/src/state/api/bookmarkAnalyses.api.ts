/**
 * Bookmark Analyses API
 *
 * Endpoints exposed by Ruth backend (Phase D.1 + D.2):
 *   POST   /api/v1/bookmark-analyses
 *   GET    /api/v1/bookmark-analyses
 *   GET    /api/v1/bookmark-analyses/{id}
 *   GET    /api/v1/bookmarks/{vas_bookmark_id}/analyses
 *   GET    /api/v1/bookmarks/{vas_bookmark_id}/preview-frame (proxy)
 */

import { apiGet, apiPost } from './client';

// ---------------------------------------------------------------------------
// Types — mirror the backend Pydantic schemas
// ---------------------------------------------------------------------------

export type BookmarkAnalysisState =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed';

export interface BookmarkAnalysisSubmitRequest {
  vas_bookmark_id: string;
  model_id: string;
  model_version?: string | null;
  parameters?: Record<string, unknown> | null;
}

/** Shape of summary.timeline entries (tank_overflow). */
export interface TimelineSample {
  timestamp_seconds: number;
  fill_percentage: number;
}

/** Shape of summary.threshold_events entries (tank_overflow). */
export interface ThresholdEvent {
  crossed_at_seconds: number;
  threshold: number;
  going_up: boolean;
}

/** Aggregate stats from a completed analysis. */
export interface AnalysisStats {
  peak_fill_percentage?: number;
  final_fill_percentage?: number;
  time_to_80_percent_seconds?: number | null;
  time_to_90_percent_seconds?: number | null;
  duration_seconds?: number;
  frames_analyzed?: number;
  frames_skipped?: number;
}

/** Tank-overflow summary blob shape. D.4 will render this; D.3 just
 *  pretty-prints the JSON. */
export interface TankOverflowSummary {
  timeline: TimelineSample[];
  threshold_events: ThresholdEvent[];
  stats: AnalysisStats;
  metadata: {
    model_id: string;
    model_version: string | null;
    sampling_fps: number;
    parameters_used: Record<string, unknown>;
  };
}

export interface BookmarkAnalysis {
  id: string;
  vas_bookmark_id: string;
  model_id: string;
  model_version: string | null;
  parameters: Record<string, unknown> | null;
  state: BookmarkAnalysisState;
  summary: TankOverflowSummary | Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  submitted_by: string | null;
}

export interface BookmarkAnalysisListItem {
  id: string;
  vas_bookmark_id: string;
  model_id: string;
  model_version: string | null;
  state: BookmarkAnalysisState;
  created_at: string;
  completed_at: string | null;
}

export interface BookmarkAnalysisListResponse {
  items: BookmarkAnalysisListItem[];
  total: number;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

const BOOKMARK_ANALYSES_PATH = '/api/v1/bookmark-analyses';

export async function submitBookmarkAnalysis(
  request: BookmarkAnalysisSubmitRequest,
): Promise<BookmarkAnalysis> {
  return apiPost<BookmarkAnalysis>(BOOKMARK_ANALYSES_PATH, request);
}

export async function getBookmarkAnalysis(id: string): Promise<BookmarkAnalysis> {
  return apiGet<BookmarkAnalysis>(`${BOOKMARK_ANALYSES_PATH}/${id}`);
}

export async function listBookmarkAnalyses(
  limit = 50,
): Promise<BookmarkAnalysisListResponse> {
  return apiGet<BookmarkAnalysisListResponse>(
    `${BOOKMARK_ANALYSES_PATH}?limit=${limit}`,
  );
}

export async function listAnalysesForBookmark(
  vasBookmarkId: string,
): Promise<BookmarkAnalysisListResponse> {
  return apiGet<BookmarkAnalysisListResponse>(
    `/api/v1/bookmarks/${vasBookmarkId}/analyses`,
  );
}

/** URL the <img> tag points at. Auth is server-side via Ruth's VAS client. */
export function getBookmarkPreviewFrameUrl(vasBookmarkId: string): string {
  return `/api/v1/bookmarks/${vasBookmarkId}/preview-frame`;
}
