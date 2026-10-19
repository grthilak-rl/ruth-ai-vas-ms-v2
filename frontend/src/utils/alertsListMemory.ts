/**
 * What the browser remembers about the Violations list.
 *
 * - The page size, per browser (localStorage): the default for a list URL
 *   that doesn't name one.
 * - The last list URL, per tab (sessionStorage): where "Back to Alerts" on a
 *   violation returns to, so it restores filters and page like browser Back.
 * - The scroll position per list URL, per tab (sessionStorage): the list
 *   scrolls inside its own pane, which router scroll restoration (window
 *   only) never sees.
 *
 * All storage access is try/catch: private mode or blocked storage must
 * degrade to defaults, never break the page.
 */

const PAGE_SIZE_KEY = 'ruth-ai-alerts-page-size';
const LIST_URL_KEY = 'ruth-ai-alerts-list-search';
const SCROLL_KEY = 'ruth-ai-alerts-scroll';
/** Keep the scroll map small: only the most recent list URLs matter. */
const MAX_SCROLL_ENTRIES = 20;

export function getStoredPageSize(fallback: number, allowed: number[]): number {
  try {
    const value = Number.parseInt(localStorage.getItem(PAGE_SIZE_KEY) ?? '', 10);
    return allowed.includes(value) ? value : fallback;
  } catch {
    return fallback;
  }
}

export function storePageSize(size: number): void {
  try {
    localStorage.setItem(PAGE_SIZE_KEY, String(size));
  } catch {
    /* storage unavailable: the URL still carries it */
  }
}

export function rememberListSearch(search: string): void {
  try {
    sessionStorage.setItem(LIST_URL_KEY, search);
  } catch {
    /* ignore */
  }
}

/** "/alerts?…" for the list as last seen in this tab, or plain "/alerts". */
export function alertsListPath(): string {
  try {
    const search = sessionStorage.getItem(LIST_URL_KEY);
    return search ? `/alerts?${search}` : '/alerts';
  } catch {
    return '/alerts';
  }
}

function readScrollMap(): Record<string, number> {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(SCROLL_KEY) ?? '{}');
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, number>)
      : {};
  } catch {
    return {};
  }
}

export function saveScrollPosition(search: string, top: number): void {
  try {
    const map = readScrollMap();
    delete map[search];
    map[search] = Math.max(0, Math.round(top));
    const keys = Object.keys(map);
    for (const key of keys.slice(0, Math.max(0, keys.length - MAX_SCROLL_ENTRIES))) delete map[key];
    sessionStorage.setItem(SCROLL_KEY, JSON.stringify(map));
  } catch {
    /* ignore */
  }
}

export function readScrollPosition(search: string): number {
  const top = readScrollMap()[search];
  return typeof top === 'number' && Number.isFinite(top) ? top : 0;
}
