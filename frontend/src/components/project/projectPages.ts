/**
 * Which pages are live (always the current project) and date formatting for
 * the project banner and list. Kept out of the component files so fast
 * refresh keeps working.
 */

/** Pages that always show the current setup, whatever project is viewed. */
const LIVE_PREFIXES = [
  '/cameras',
  '/bookmark-monitoring',
  '/bookmark-analyses',
  '/settings/models',
  '/settings/system',
  '/settings/branding',
];

export function isLivePage(pathname: string): boolean {
  return LIVE_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function formatDay(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}
