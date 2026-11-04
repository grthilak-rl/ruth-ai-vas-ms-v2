/**
 * Customer report (PDF) and report branding.
 *
 * Admin-gated like the evidence export: the report carries cropped frames of
 * identifiable workers, and the recent list names who generated each report.
 * Raw-data exports on the same page keep using the open analytics API.
 */

import { ADMIN_API_PREFIX, adminFetch, getAdminToken } from '../../pages/admin/adminApi';
import { buildApiUrl } from '../../config/api';

export type ReportPreset = 'daily' | 'weekly' | 'custom' | 'shift';
export type ReportMode = 'all' | 'verified';

export interface CustomerReportRequest {
  format: 'pdf';
  preset: ReportPreset;
  /** Daily and shift: the shift day. Weekly: the last of its 7 shift days. */
  day?: string | null;
  /** Shift: the shift's name, from the schedule. */
  shift?: string | null;
  /** Custom: local dates, both included. */
  start?: string | null;
  end?: string | null;
  mode: ReportMode;
  gallery: boolean;
  gallery_size: number;
  /** Incident keys removed from the gallery; the next candidates fill in. */
  gallery_exclude?: string[];
}

export interface GalleryCandidate {
  key: string;
  /** Its saved frame's violation; thumbnail via galleryThumbUrl. */
  violation_id: string | null;
  area: string;
  camera: string;
  type_label: string;
  severity: string;
  /** Site time zone, e.g. "Wed 28 Oct, 07:05". */
  started: string;
  minutes: number;
  detections: number;
}

export interface GalleryPreview {
  items: GalleryCandidate[];
  incidents: number;
}

export interface CustomerReportJob {
  id: string;
  status: 'building' | 'ready' | 'failed' | 'expired';
  error: string | null;
  stage: string | null;
  done: number;
  total: number;
  format: string;
  preset: ReportPreset;
  mode: ReportMode;
  period_start: string;
  period_end: string;
  period_label: string;
  options: Partial<CustomerReportRequest>;
  /** manual, auto (the shift scheduler) or regenerate. */
  trigger: 'manual' | 'auto' | 'regenerate';
  shift_name: string | null;
  regenerated_from: string | null;
  attempts: number;
  /** Violations in the period dismissed after this report was built. */
  dismissed_since: number;
  filename: string | null;
  size_bytes: number | null;
  incidents: number | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
}

export interface CustomerReportDefaults {
  timezone: string;
  /** "07:00" when report days follow the first shift, else "00:00". */
  day_start: string;
  /** The most recent shift day that has ended, YYYY-MM-DD. */
  last_complete_day: string;
  project_started_on: string | null;
  max_custom_days: number;
  retention_days: number;
  gallery_sizes: number[];
  default_gallery_size: number;
  shifts: { name: string; start: string; end: string }[];
  /** The most recent shift that has ended. */
  last_complete_shift_day: string | null;
  last_complete_shift: string | null;
}

export interface AutoReportSettings {
  enabled: boolean;
  settle_minutes: number;
  enabled_at: string | null;
  updated_by: string | null;
  /** Why the scheduler is doing nothing right now, if it is. */
  idle_reason: string | null;
  last_tick_at: string | null;
}

export interface ReportBranding {
  customer_name: string | null;
  has_logo: boolean;
  updated_by: string | null;
  updated_at: string | null;
}

const REPORTS = `${ADMIN_API_PREFIX}/customer-reports`;
const BRANDING = `${ADMIN_API_PREFIX}/report-branding`;

export const MAX_LOGO_BYTES = 1024 * 1024;

export function getReportDefaults(): Promise<CustomerReportDefaults> {
  return adminFetch<CustomerReportDefaults>(`${REPORTS}/defaults`);
}

export function previewGallery(body: CustomerReportRequest): Promise<GalleryPreview> {
  return adminFetch<GalleryPreview>(`${REPORTS}/gallery-preview`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** The cropped card thumbnail the Violations page uses (open endpoint). */
export function galleryThumbUrl(violationId: string): string {
  return buildApiUrl(`/api/v1/violations/${violationId}/frame/thumb`);
}

export function createCustomerReport(body: CustomerReportRequest): Promise<CustomerReportJob> {
  return adminFetch<CustomerReportJob>(REPORTS, { method: 'POST', body: JSON.stringify(body) });
}

export function getCustomerReport(id: string): Promise<CustomerReportJob> {
  return adminFetch<CustomerReportJob>(`${REPORTS}/${id}`);
}

export function regenerateCustomerReport(id: string): Promise<CustomerReportJob> {
  return adminFetch<CustomerReportJob>(`${REPORTS}/${id}/regenerate`, { method: 'POST' });
}

export function getAutoReportSettings(): Promise<AutoReportSettings> {
  return adminFetch<AutoReportSettings>(`${REPORTS}/auto-settings`);
}

export function setAutoReportSettings(enabled: boolean, settleMinutes: number): Promise<AutoReportSettings> {
  return adminFetch<AutoReportSettings>(`${REPORTS}/auto-settings`, {
    method: 'PUT',
    body: JSON.stringify({ enabled, settle_minutes: settleMinutes }),
  });
}

export function listCustomerReports(limit = 20): Promise<{ items: CustomerReportJob[]; total: number }> {
  return adminFetch(`${REPORTS}?limit=${limit}`);
}

/** Fetch an authenticated file and hand it to the browser as a download. */
async function downloadAuthenticated(path: string, filename: string): Promise<void> {
  const token = getAdminToken();
  if (!token) throw new Error('Not signed in');
  const response = await fetch(buildApiUrl(path), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (response.status === 410) throw new Error('This report is no longer on the server');
  if (!response.ok) throw new Error(`Download failed (${response.status})`);
  const url = URL.createObjectURL(await response.blob());
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    // Next tick: Safari needs the click processed before the URL goes.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

export function downloadCustomerReport(job: CustomerReportJob): Promise<void> {
  return downloadAuthenticated(
    `${REPORTS}/${job.id}/download`,
    job.filename ?? `safety-report-${job.id}.pdf`
  );
}

export function getReportBranding(): Promise<ReportBranding> {
  return adminFetch<ReportBranding>(BRANDING);
}

export function setCustomerName(customerName: string): Promise<ReportBranding> {
  return adminFetch<ReportBranding>(BRANDING, {
    method: 'PUT',
    body: JSON.stringify({ customer_name: customerName }),
  });
}

/** The image is the request body: one file, no form fields. */
export function uploadLogo(file: File): Promise<ReportBranding> {
  return adminFetch<ReportBranding>(`${BRANDING}/logo`, {
    method: 'PUT',
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
    body: file,
  });
}

export function deleteLogo(): Promise<ReportBranding> {
  return adminFetch<ReportBranding>(`${BRANDING}/logo`, { method: 'DELETE' });
}

/** The stored logo as an object URL for the preview; the caller revokes it. */
export async function fetchLogoUrl(): Promise<string | null> {
  const token = getAdminToken();
  if (!token) return null;
  const response = await fetch(buildApiUrl(`${BRANDING}/logo`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) return null;
  return URL.createObjectURL(await response.blob());
}
