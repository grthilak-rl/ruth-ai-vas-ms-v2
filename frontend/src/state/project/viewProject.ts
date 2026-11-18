/**
 * Project view mode: which project the portal is reading.
 *
 * The selection lives in the page URL as `?project=<slug>` (so links and
 * refreshes keep it) and in this module (so every request made between a
 * navigation and the URL being re-synced still carries it).
 *
 * Every backend call is tagged in ONE place: `installProjectFetch` wraps
 * `window.fetch` and adds `X-Ruth-Project` to same-origin `/api/v1/` requests
 * while a past project is open. That covers the API client, the admin
 * client, the analytics service and the download helpers alike — the same
 * reason the backend scopes reads with one hook instead of ~90 filters.
 * The backend honours the header only on project-scoped paths (Violations,
 * Analytics, Reports, exports); live pages (Cameras, live view, System
 * Health) always read the current project whatever is sent.
 */

import { isLivePage } from '../../components/project/projectPages';

export const PROJECT_PARAM = 'project';
export const PROJECT_HEADER = 'X-Ruth-Project';

let viewed: string | null = null;
const listeners = new Set<(slug: string | null) => void>();

/** Slug of the past project being viewed, or null for the current project. */
export function getViewedProject(): string | null {
  return viewed;
}

export function setViewedProject(slug: string | null): void {
  const next = slug && slug.trim() ? slug.trim() : null;
  if (next === viewed) return;
  viewed = next;
  listeners.forEach((fn) => fn(viewed));
}

export function subscribeViewedProject(fn: (slug: string | null) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** The project named in a query string (`?project=hpcl`), or null. */
export function projectFromSearch(search: string): string | null {
  const value = new URLSearchParams(search).get(PROJECT_PARAM);
  return value && value.trim() ? value.trim() : null;
}

/** `search` with the project param set to `slug` (or removed for null). */
export function withProject(search: string, slug: string | null): string {
  const params = new URLSearchParams(search);
  if (slug) params.set(PROJECT_PARAM, slug);
  else params.delete(PROJECT_PARAM);
  const s = params.toString();
  return s ? `?${s}` : '';
}

/** Does this request go to Ruth's own API (where the header means something)? */
export function isRuthApi(url: string, origin: string): boolean {
  try {
    const u = new URL(url, origin);
    return u.origin === origin && u.pathname.startsWith('/api/v1/');
  } catch {
    return false;
  }
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

let installed = false;

/**
 * Wrap window.fetch once, at startup. Reads the initial selection from the
 * page URL so the very first requests after a reload are already tagged.
 */
export function installProjectFetch(win: Window & typeof globalThis = window): void {
  if (installed) return;
  installed = true;
  setViewedProject(projectFromSearch(win.location.search));
  const original = win.fetch.bind(win);
  win.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const slug = viewed;
    // Live pages (Cameras, live view, System Health) show the current
    // project whatever is viewed, so their requests are never tagged.
    if (!slug || isLivePage(win.location.pathname) || !isRuthApi(requestUrl(input), win.location.origin)) {
      return original(input, init);
    }
    const headers = new Headers(
      init?.headers ?? (input instanceof Request ? input.headers : undefined)
    );
    if (!headers.has(PROJECT_HEADER)) headers.set(PROJECT_HEADER, slug);
    return original(input, { ...init, headers });
  };
}

/** Test hook: forget the installation (the wrapped fetch stays). */
export function _resetForTests(): void {
  installed = false;
  viewed = null;
  listeners.clear();
}
