/**
 * Analytics API Client
 *
 * Provides API functions for analytics endpoints.
 * Aligned with analytics-design.md §8 API Requirements.
 *
 * All endpoints are under /api/v1/analytics
 */

import type {
  AnalyticsSummaryResponse,
  ViolationTrendsResponse,
  DeviceStatusResponse,
  ExportRequest,
} from '../types/analytics';

/**
 * Get analytics summary with breakdowns
 *
 * GET /api/v1/analytics/summary
 *
 * @param from - Start of time range (ISO 8601)
 * @param to - End of time range (ISO 8601)
 * @param granularity - Time series granularity ('hour' or 'day')
 */
export async function getAnalyticsSummary(
  from?: string,
  to?: string,
  granularity: 'hour' | 'day' = 'hour'
): Promise<AnalyticsSummaryResponse> {
  const params = new URLSearchParams();
  if (from) params.set('from', from);
  if (to) params.set('to', to);
  params.set('granularity', granularity);

  const response = await fetch(`/api/v1/analytics/summary?${params}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch analytics summary: ${response.status}`);
  }

  return response.json();
}

/**
 * Get violation trends over time
 *
 * GET /api/v1/analytics/violations/trends
 *
 * @param from - Start of time range (ISO 8601)
 * @param to - End of time range (ISO 8601)
 * @param granularity - Time bucket size ('minute', 'hour', or 'day')
 * @param cameraId - Optional camera filter
 * @param violationType - Optional violation type filter
 */
export async function getViolationTrends(
  from?: string,
  to?: string,
  granularity: 'minute' | 'hour' | 'day' = 'hour',
  cameraId?: string,
  violationType?: string
): Promise<ViolationTrendsResponse> {
  const params = new URLSearchParams();
  if (from) params.set('from', from);
  if (to) params.set('to', to);
  params.set('granularity', granularity);
  if (cameraId) params.set('camera_id', cameraId);
  if (violationType) params.set('violation_type', violationType);

  const response = await fetch(`/api/v1/analytics/violations/trends?${params}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch violation trends: ${response.status}`);
  }

  return response.json();
}

/**
 * Get per-device analytics status
 *
 * GET /api/v1/analytics/devices/status
 *
 * @param from - Start of time range (ISO 8601)
 * @param to - End of time range (ISO 8601)
 */
export async function getDeviceStatus(
  from?: string,
  to?: string
): Promise<DeviceStatusResponse> {
  const params = new URLSearchParams();
  if (from) params.set('from', from);
  if (to) params.set('to', to);

  const response = await fetch(`/api/v1/analytics/devices/status?${params}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch device status: ${response.status}`);
  }

  return response.json();
}

/**
 * Export analytics data
 *
 * POST /api/v1/analytics/export
 *
 * Downloads a file in the requested format (CSV, XLSX, or PDF).
 *
 * @param request - Export configuration
 * @returns Blob containing the file data
 */
export async function exportAnalytics(request: ExportRequest): Promise<Blob> {
  const response = await fetch('/api/v1/analytics/export', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    // Try to parse error response
    const contentType = response.headers.get('content-type');
    if (contentType?.includes('application/json')) {
      const errorData = await response.json();
      throw new Error(
        errorData.error_description || `Export failed: ${response.status}`
      );
    }
    throw new Error(`Export failed: ${response.status}`);
  }

  return response.blob();
}

/**
 * Helper: Download a blob as a file
 *
 * Creates a temporary anchor element to trigger file download.
 *
 * @param blob - File blob
 * @param filename - Suggested filename
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Helper: Generate filename for export
 *
 * Format: ruth-ai-analytics-{date}.{ext}
 *
 * @param format - Export format
 * @returns Generated filename
 */
export function generateExportFilename(
  format: 'csv' | 'xlsx' | 'pdf'
): string {
  const date = new Date().toISOString().split('T')[0]; // YYYY-MM-DD
  return `ruth-ai-analytics-${date}.${format}`;
}

/**
 * Helper: Calculate time range for preset
 *
 * @param preset - Time range preset
 * @returns { from, to } in ISO 8601 format
 */
export function calculateTimeRange(
  preset: '24h' | '7d' | '30d'
): { from: string; to: string } {
  const now = new Date();
  const to = now.toISOString();

  let from: Date;
  switch (preset) {
    case '24h':
      from = new Date(now.getTime() - 24 * 60 * 60 * 1000);
      break;
    case '7d':
      from = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      break;
    case '30d':
      from = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      break;
  }

  return {
    from: from.toISOString(),
    to,
  };
}

/**
 * Helper: Validate time range
 *
 * Per analytics-design.md, maximum time range is 90 days.
 *
 * @param from - Start date
 * @param to - End date
 * @returns Error message if invalid, null if valid
 */
export function validateTimeRange(from: Date, to: Date): string | null {
  if (from >= to) {
    return 'Start date must be before end date';
  }

  const maxDays = 90;
  const rangeDays = (to.getTime() - from.getTime()) / (24 * 60 * 60 * 1000);

  if (rangeDays > maxDays) {
    return `Time range exceeds maximum of ${maxDays} days`;
  }

  return null;
}
