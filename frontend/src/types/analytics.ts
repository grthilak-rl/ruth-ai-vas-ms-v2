/**
 * Analytics Domain Types
 *
 * Aligned with analytics-design.md §8 and backend schemas.
 * Per F6 §6 Analytics Domain.
 */

export interface TimeRange {
  from: string; // ISO 8601
  to: string; // ISO 8601
}

export interface AnalyticsTotals {
  violations_total: number;
  violations_open: number;
  violations_reviewed: number;
  violations_dismissed: number;
  violations_resolved: number;
  cameras_active: number;
  cameras_total: number;
}

export interface AnalyticsComparison {
  violations_total_change: number;
  violations_total_change_percent: number;
}

export interface CameraBreakdown {
  camera_id: string;
  camera_name: string;
  violations_total: number;
  violations_open: number;
  violations_reviewed: number;
  violations_dismissed: number;
  violations_resolved: number;
}

export interface TypeBreakdown {
  type: string;
  type_display: string;
  count: number;
  percentage: number;
}

export interface StatusBreakdown {
  status: string;
  count: number;
  percentage: number;
}

export interface TimeSeriesBucket {
  bucket: string; // ISO 8601
  total: number;
  by_type: Record<string, number>;
}

export interface AnalyticsSummaryResponse {
  time_range: TimeRange;
  totals: AnalyticsTotals;
  comparison: AnalyticsComparison | null;
  by_camera: CameraBreakdown[];
  by_type: TypeBreakdown[];
  by_status: StatusBreakdown[];
  time_series: TimeSeriesBucket[];
  generated_at: string; // ISO 8601
}

// Violation Trends API

export interface ViolationTrendBucket {
  bucket: string; // ISO 8601
  total: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
}

export interface ViolationTrendsResponse {
  time_range: TimeRange;
  granularity: 'minute' | 'hour' | 'day';
  data: ViolationTrendBucket[];
  generated_at: string; // ISO 8601
}

// Device Status API

export interface DeviceAnalytics {
  camera_id: string;
  camera_name: string;
  violations_total: number;
  violations_by_status: Record<string, number>;
  violations_by_type: Record<string, number>;
  avg_confidence: number;
  last_violation_at: string | null; // ISO 8601
}

export interface DeviceStatusSummary {
  total_violations: number;
  total_cameras: number;
  active_cameras: number;
}

export interface DeviceStatusResponse {
  time_range: TimeRange;
  devices: DeviceAnalytics[];
  summary: DeviceStatusSummary;
  generated_at: string; // ISO 8601
}

// Export API

export type ExportFormat = 'csv' | 'xlsx' | 'pdf';

export interface ExportScope {
  all: boolean;
  camera_ids?: string[];
  violation_types?: string[];
  statuses?: string[];
}

export interface ExportOptions {
  include_headers: boolean;
  include_timestamps: boolean;
  include_raw_confidence: boolean;
  include_evidence_urls: boolean;
  include_bounding_boxes: boolean;
}

export interface ExportRequest {
  format: ExportFormat;
  time_range: TimeRange;
  scope: ExportScope;
  options: ExportOptions;
}

// Time range presets

export type TimeRangePreset = '24h' | '7d' | '30d' | 'custom';

export interface TimeRangeSelection {
  preset: TimeRangePreset;
  from?: Date;
  to?: Date;
}

// Chart data helpers

export interface ChartDataPoint {
  label: string;
  value: number;
}

export interface LineChartSeries {
  name: string;
  data: Array<{ x: Date; y: number }>;
  color?: string;
}
