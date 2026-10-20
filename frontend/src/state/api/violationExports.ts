/**
 * Bulk evidence export ("Download snapshots" on the Violations page).
 *
 * Admin-gated on both ends: creating an export and downloading it both
 * require a valid admin token, because the archive is hundreds of megabytes
 * of identifiable worker imagery in a single shareable file. The Violations
 * page itself stays open, as it is today.
 */

import { ADMIN_API_PREFIX, adminFetch, getAdminToken } from '../../pages/admin/adminApi';
import { buildApiUrl } from '../../config/api';

export type ExportScope = 'all' | 'one_per_incident';

export interface ExportFilters {
  statuses?: string[] | null;
  camera_id?: string | null;
  since?: string | null;
  until?: string | null;
  violation_type?: string | null;
  type_detail?: string | null;
  severities?: string[] | null;
  area?: string | null;
}

export interface ExportRequestBody {
  filters: ExportFilters;
  scope: ExportScope;
  annotated: boolean;
  include_snapshots: boolean;
  incident_ids?: string[] | null;
}

export interface ExportPreview {
  violations_matching_filters: number;
  violations_in_export: number;
  without_inferred_frame: number;
  estimated_bytes: number;
  max_violations: number;
  within_cap: boolean;
}

export interface ExportJob {
  id: string;
  status: 'building' | 'ready' | 'failed' | 'expired';
  error: string | null;
  total: number;
  done: number;
  images: number;
  without_inferred_frame: number;
  skipped: number;
  size_bytes: number | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
}

const BASE = `${ADMIN_API_PREFIX}/violation-exports`;

export function previewExport(body: ExportRequestBody): Promise<ExportPreview> {
  return adminFetch<ExportPreview>(`${BASE}/preview`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function createExport(body: ExportRequestBody): Promise<ExportJob> {
  return adminFetch<ExportJob>(BASE, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function getExport(id: string): Promise<ExportJob> {
  return adminFetch<ExportJob>(`${BASE}/${id}`);
}

/**
 * Pull the archive and hand it to the browser as a download.
 *
 * Not a plain link: the endpoint needs an Authorization header, so the
 * bytes come through fetch and go out again as a blob. That does mean the
 * whole archive passes through memory, which is why the server caps an
 * export at 5,000 violations.
 */
export async function downloadExport(id: string, suggestedName: string): Promise<void> {
  const token = getAdminToken();
  if (!token) throw new Error('Not signed in');

  const response = await fetch(buildApiUrl(`${BASE}/${id}/download`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(`Download failed (${response.status})`);
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = suggestedName;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    // Revoked on the next tick: Safari needs the click to have been
    // processed before the object URL goes away.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}
