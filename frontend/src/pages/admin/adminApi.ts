/**
 * Admin-only API wrapper (Model Management area).
 *
 * Deliberately separate from state/api/client.ts, which stays the client for
 * the rest of the app. The admin token lives under its own sessionStorage key
 * and is attached ONLY to /api/v1/admin requests made from admin pages, so no
 * existing request ever carries it and AuthContext is untouched.
 *
 * sessionStorage: the token is dropped when the tab closes and is not shared
 * across tabs. The server issues 8-hour tokens.
 */

import { buildApiUrl } from '../../config/api';

export const ADMIN_TOKEN_KEY = 'ruth_admin_token';
export const ADMIN_LOGIN_PATH = '/admin/login';
export const ADMIN_HOME_PATH = '/admin/models';

const ADMIN_API_PREFIX = '/api/v1/admin';
const TIMEOUT_MS = 30_000;

// ============================================================================
// Token storage (storage can throw in private mode or when disabled)
// ============================================================================

export function getAdminToken(): string | null {
  try {
    return sessionStorage.getItem(ADMIN_TOKEN_KEY);
  } catch {
    return null;
  }
}

function setAdminToken(token: string): void {
  try {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
  } catch {
    // Without storage the admin must sign in again on each page load.
  }
}

export function clearAdminToken(): void {
  try {
    sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch {
    // Nothing stored.
  }
}

// ============================================================================
// Errors
// ============================================================================

export class AdminApiError extends Error {
  readonly status: number;
  readonly retryAfterSeconds?: number;

  constructor(status: number, message: string, retryAfterSeconds?: number) {
    super(message);
    this.name = 'AdminApiError';
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

async function errorFromResponse(response: Response): Promise<AdminApiError> {
  let message = response.statusText || `HTTP ${response.status}`;
  try {
    const body = await response.json();
    if (typeof body?.detail?.message === 'string') {
      message = body.detail.message;
    }
  } catch {
    // Non-JSON error body; keep the status text.
  }
  const retryAfter = Number(response.headers.get('Retry-After'));
  return new AdminApiError(
    response.status,
    message,
    Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined
  );
}

// ============================================================================
// Navigation helpers
// ============================================================================

/** Only same-origin admin paths are accepted as a post-login destination. */
export function safeNextPath(next: string | null): string {
  if (
    next &&
    next.startsWith('/admin/') &&
    !next.startsWith('//') &&
    !next.startsWith(ADMIN_LOGIN_PATH)
  ) {
    return next;
  }
  return ADMIN_HOME_PATH;
}

export function adminLoginUrl(returnTo?: string): string {
  const next = returnTo ? safeNextPath(returnTo) : ADMIN_HOME_PATH;
  return next === ADMIN_HOME_PATH
    ? ADMIN_LOGIN_PATH
    : `${ADMIN_LOGIN_PATH}?next=${encodeURIComponent(next)}`;
}

function redirectToAdminLogin(): void {
  window.location.replace(adminLoginUrl(window.location.pathname + window.location.search));
}

// ============================================================================
// Requests
// ============================================================================

async function send(path: string, init: RequestInit): Promise<Response> {
  if (!path.startsWith(ADMIN_API_PREFIX)) {
    // This wrapper exists only for the admin API; everything else uses client.ts.
    throw new Error(`adminApi only handles ${ADMIN_API_PREFIX} paths, got ${path}`);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    return await fetch(buildApiUrl(path), { ...init, signal: controller.signal });
  } catch {
    throw new AdminApiError(0, 'Unable to reach the server');
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Authenticated admin request. On 401 (missing, expired or invalid token) the
 * token is cleared and the browser is sent to the admin login page.
 */
export async function adminFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getAdminToken();
  if (!token) {
    redirectToAdminLogin();
    throw new AdminApiError(401, 'Not signed in');
  }

  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${token}`);
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await send(path, { ...init, headers });
  if (response.status === 401) {
    clearAdminToken();
    redirectToAdminLogin();
    throw await errorFromResponse(response);
  }
  if (!response.ok) {
    throw await errorFromResponse(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

// ============================================================================
// Endpoints
// ============================================================================

export interface AdminLoginResponse {
  access_token: string;
  token_type: 'bearer';
  expires_at: string;
  username: string;
}

export interface AdminMe {
  username: string;
  role: string;
  expires_at: string;
}

/**
 * Exchange credentials for a token and store it. A 401 here means wrong
 * credentials, so unlike adminFetch it does not redirect.
 */
export async function adminLogin(username: string, password: string): Promise<AdminLoginResponse> {
  const response = await send(`${ADMIN_API_PREFIX}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    throw await errorFromResponse(response);
  }
  const body = (await response.json()) as AdminLoginResponse;
  setAdminToken(body.access_token);
  return body;
}

export function fetchAdminMe(): Promise<AdminMe> {
  return adminFetch<AdminMe>(`${ADMIN_API_PREFIX}/me`);
}

// ============================================================================
// Model store (/api/v1/admin/model-store)
// ============================================================================

const STORE = `${ADMIN_API_PREFIX}/model-store`;

export interface StoreFile {
  id: string;
  filename: string;
  size_bytes: number;
  sha256: string;
  uploaded_at: string;
  uploaded_by: string | null;
  status: 'uploaded';
}

export interface StoreUpload {
  id: string;
  model_pk: string;
  filename: string;
  size_bytes: number;
  chunk_size: number;
  total_chunks: number;
  received_chunks: number[];
  status: string;
  error: string | null;
  client_last_modified: number | null;
  created_at: string;
  updated_at: string;
}

export interface StoreModelSummary {
  id: string;
  model_id: string;
  display_name: string;
  state: string;
  model_id_editable: boolean;
  file_count: number;
  total_bytes: number;
  status: 'no_files' | 'uploaded';
  created_at: string;
  created_by: string | null;
}

export interface StoreModelDetail extends StoreModelSummary {
  files: StoreFile[];
  active_uploads: StoreUpload[];
}

export function listStoreModels(): Promise<StoreModelSummary[]> {
  return adminFetch<{ models: StoreModelSummary[] }>(`${STORE}/models`).then((r) => r.models);
}

export function createStoreModel(displayName: string): Promise<StoreModelDetail> {
  return adminFetch<StoreModelDetail>(`${STORE}/models`, {
    method: 'POST',
    body: JSON.stringify({ display_name: displayName }),
  });
}

export function getStoreModel(modelPk: string): Promise<StoreModelDetail> {
  return adminFetch<StoreModelDetail>(`${STORE}/models/${modelPk}`);
}

export function deleteStoreModel(modelPk: string): Promise<void> {
  return adminFetch<void>(`${STORE}/models/${modelPk}`, { method: 'DELETE' });
}

export function deleteStoreFile(modelPk: string, fileId: string): Promise<void> {
  return adminFetch<void>(`${STORE}/models/${modelPk}/files/${fileId}`, { method: 'DELETE' });
}

export function initUpload(
  modelPk: string,
  file: { name: string; size: number; lastModified: number }
): Promise<StoreUpload> {
  return adminFetch<StoreUpload>(`${STORE}/models/${modelPk}/uploads`, {
    method: 'POST',
    body: JSON.stringify({
      filename: file.name,
      size_bytes: file.size,
      last_modified: file.lastModified,
    }),
  });
}

export function completeUpload(uploadId: string): Promise<{ upload_id: string; file: StoreFile }> {
  return adminFetch(`${STORE}/uploads/${uploadId}/complete`, { method: 'POST' });
}

export function abortUpload(uploadId: string): Promise<void> {
  return adminFetch<void>(`${STORE}/uploads/${uploadId}`, { method: 'DELETE' });
}

/**
 * PUT one chunk with byte-level progress. XMLHttpRequest rather than fetch:
 * fetch exposes no upload progress. Same auth and 401 handling as adminFetch.
 */
export function putChunk(
  uploadId: string,
  index: number,
  data: Blob,
  onProgress: (loadedBytes: number) => void,
  signal?: AbortSignal
): Promise<void> {
  const token = getAdminToken();
  if (!token) {
    redirectToAdminLogin();
    return Promise.reject(new AdminApiError(401, 'Not signed in'));
  }
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', buildApiUrl(`${STORE}/uploads/${uploadId}/chunks/${index}`));
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.timeout = 300_000;
    xhr.upload.onprogress = (event) => onProgress(event.loaded);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
        return;
      }
      if (xhr.status === 401) {
        clearAdminToken();
        redirectToAdminLogin();
      }
      let message = xhr.statusText || `HTTP ${xhr.status}`;
      try {
        const body = JSON.parse(xhr.responseText);
        if (typeof body?.detail?.message === 'string') message = body.detail.message;
      } catch {
        // Non-JSON body (e.g. nginx 413 page).
      }
      reject(new AdminApiError(xhr.status, message));
    };
    xhr.onerror = () => reject(new AdminApiError(0, 'Network error'));
    xhr.ontimeout = () => reject(new AdminApiError(0, 'Upload timed out'));
    xhr.onabort = () => reject(new AdminApiError(0, 'Cancelled'));
    signal?.addEventListener('abort', () => xhr.abort(), { once: true });
    xhr.send(data);
  });
}
