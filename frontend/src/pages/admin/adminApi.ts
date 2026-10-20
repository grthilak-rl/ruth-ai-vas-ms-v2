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

/** Where the standalone login page lands when no `next` was given. */
export const ADMIN_HOME_PATH = '/settings/models';

/**
 * Called whenever the token is cleared because the server rejected it.
 *
 * Admin controls now live inside Settings, a page that works perfectly well
 * signed out. A 401 there must put the affected section back into its
 * signed-out state and leave the operator where they are — the old
 * behaviour, a hard `location.replace` to /admin/login, would throw them
 * out of the page mid-task and lose everything else on it.
 *
 * Set by SettingsLayout. Unset (the standalone pages) keeps the redirect,
 * which is still right for a page that is nothing but admin content.
 */
type SessionExpiredHandler = () => void;
let onSessionExpired: SessionExpiredHandler | null = null;

export function setSessionExpiredHandler(handler: SessionExpiredHandler | null): void {
  onSessionExpired = handler;
}

export const ADMIN_API_PREFIX = '/api/v1/admin';
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

/**
 * Only same-origin admin destinations are accepted after login.
 *
 * `/settings/` joined `/admin/` here when the admin pages moved into
 * Settings. Both are allowed: `/admin/*` still resolves (as redirects) so
 * old bookmarks and any link already in the wild keep working.
 *
 * The `//` check matters — `//evil.example` is a protocol-relative URL that
 * `startsWith('/settings/')` would otherwise have to reject on its own.
 */
const ALLOWED_NEXT_PREFIXES = ['/settings/', '/admin/'] as const;

export function safeNextPath(next: string | null): string {
  if (
    next &&
    !next.startsWith('//') &&
    !next.startsWith(ADMIN_LOGIN_PATH) &&
    ALLOWED_NEXT_PREFIXES.some((prefix) => next.startsWith(prefix))
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

/**
 * The token was rejected or is missing. Clear it and recover.
 *
 * Inside Settings the handler re-renders the admin sections as signed out,
 * in place. Everywhere else we fall back to the login page.
 *
 * Clearing first, unconditionally, is what makes this safe against a
 * redirect loop: the login page itself never calls adminFetch, and by the
 * time anything else re-runs there is no token to be rejected a second
 * time. A section that re-queries after this gets its signed-out branch,
 * not another 401.
 */
function handleSessionExpired(): void {
  clearAdminToken();
  if (onSessionExpired) {
    onSessionExpired();
    return;
  }
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
 * token is cleared and the session-expired handler runs: inside Settings
 * that re-renders the admin sections as signed out; elsewhere it redirects
 * to the admin login page.
 */
export async function adminFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getAdminToken();
  if (!token) {
    handleSessionExpired();
    throw new AdminApiError(401, 'Not signed in');
  }

  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${token}`);
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await send(path, { ...init, headers });
  if (response.status === 401) {
    handleSessionExpired();
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
  /**
   * Whether the store runtime is actually serving this model. Distinct from
   * `status`, which only says whether the weight files were uploaded — a
   * model can be fully uploaded and still not be running. Null when no
   * store runtime is configured.
   */
  runtime?: StoreModelRuntime | null;
}

export type StoreModelRuntimeState =
  | 'running'
  | 'not_loaded'
  | 'not_installed'
  | 'unreachable';

export interface StoreModelRuntime {
  state: StoreModelRuntimeState;
  version?: string | null;
  detail?: string | null;
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
    handleSessionExpired();
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
        handleSessionExpired();
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

// ============================================================================
// Projects (/api/v1/admin/projects)
// ============================================================================

const PROJECTS = `${ADMIN_API_PREFIX}/projects`;

/** Longer than the shared TIMEOUT_MS: pg_dump plus the archive transaction. */
const START_PROJECT_TIMEOUT_MS = 20 * 60_000;

export interface ProjectSummary {
  id: string;
  name: string;
  slug: string;
  state: 'active' | 'archived';
  started_at: string;
  started_by: string;
  ended_at: string | null;
  ended_by: string | null;
  archive_batch_id: string | null;
  archived_counts: Record<string, number> | null;
  backup_path: string | null;
}

export interface LiveCameraInfo {
  device_id: string;
  camera_name: string;
  session_id: string;
  state: string;
}

/** Machine-readable preflight refusals; see PreflightResponse on the server. */
export type ProjectBlocker =
  | 'inference_active'
  | 'too_much_data'
  | 'backup_unavailable';

export interface ProjectPreflight {
  can_proceed: boolean;
  blockers: ProjectBlocker[];
  current_project: ProjectSummary | null;
  row_counts: Record<string, number>;
  total_rows: number;
  live_cameras: LiveCameraInfo[];
  backup_dir: string;
  evidence_with_vas_media: number;
}

export interface StartProjectResult {
  new_project: ProjectSummary;
  archived_project: ProjectSummary | null;
  archive_batch_id: string | null;
  archived_counts: Record<string, number>;
  backup_path: string | null;
  stopped_cameras: string[];
  vas_paths_resolved: number;
  vas_paths_missing: number;
  message: string;
}

export function listProjects(): Promise<{
  items: ProjectSummary[];
  active: ProjectSummary | null;
}> {
  return adminFetch(PROJECTS);
}

/**
 * What starting a new project would archive, and anything blocking it.
 *
 * `stopInference` previews the result assuming live inference is stopped
 * first, so ticking the checkbox re-measures rather than guessing.
 */
export function fetchProjectPreflight(stopInference = false): Promise<ProjectPreflight> {
  const query = stopInference ? '?stop_inference=true' : '';
  return adminFetch(`${PROJECTS}/preflight${query}`);
}

/**
 * Archive the current project and start a new one.
 *
 * Not routed through adminFetch: the default 30s timeout is far too short
 * for a pg_dump of a 150 MB database followed by the archive transaction.
 */
export async function startNewProject(body: {
  name: string;
  confirm_name: string;
  stop_inference: boolean;
  confirm_large?: boolean;
}): Promise<StartProjectResult> {
  const token = getAdminToken();
  if (!token) {
    handleSessionExpired();
    throw new AdminApiError(401, 'Not signed in');
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), START_PROJECT_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(buildApiUrl(`${PROJECTS}/start`), {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch {
    // A timeout here does NOT mean the archive failed — it runs in one
    // transaction server-side and may well have committed. Say so, rather
    // than inviting a retry that would then be refused for a duplicate name.
    throw new AdminApiError(
      0,
      'The request timed out. The archive may still have completed — reload ' +
        'the project list before trying again.'
    );
  } finally {
    clearTimeout(timer);
  }

  if (response.status === 401) {
    handleSessionExpired();
    throw await errorFromResponse(response);
  }
  if (!response.ok) {
    throw await errorFromResponse(response);
  }
  return (await response.json()) as StartProjectResult;
}
