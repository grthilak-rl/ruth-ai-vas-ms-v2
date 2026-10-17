import { useCallback, useSyncExternalStore } from 'react';
import { ADMIN_TOKEN_KEY, clearAdminToken, getAdminToken } from './adminApi';

/**
 * The admin token as React state.
 *
 * Before the Settings consolidation the token was only ever read
 * imperatively — a route guard called getAdminToken() once on navigation,
 * and nothing re-rendered when it changed. That was enough when signing in
 * meant a full page navigation.
 *
 * It is not enough now: Settings is one page where admin and non-admin
 * sections sit side by side, so signing in (or a token expiring mid-page)
 * has to re-render the sections in place, with no navigation. This makes
 * the token an observable store that components can subscribe to.
 *
 * Deliberately not React Context: the token lives in sessionStorage, which
 * is the real source of truth and is also written by adminApi on a 401.
 * Mirroring it into a provider would create two sources that can disagree.
 * useSyncExternalStore reads the storage every time and re-renders only
 * when a notification says it may have changed.
 */

type Listener = () => void;

const listeners = new Set<Listener>();

/** Notify every subscribed component that the token may have changed. */
export function notifyAdminSessionChanged(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);

  // Another tab signing in or out writes the same sessionStorage key.
  // sessionStorage is per-tab so this mostly matters for duplicated tabs,
  // but it costs nothing and prevents a stale "signed out" section.
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === ADMIN_TOKEN_KEY) listener();
  };
  window.addEventListener('storage', onStorage);

  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

/**
 * getSnapshot must return a referentially stable value or React re-renders
 * forever. The token is a string|null, which compares by value — so this is
 * safe exactly because we return the raw token and not an object wrapping
 * it. The hook below derives the object AFTER the snapshot comparison.
 */
function getSnapshot(): string | null {
  return getAdminToken();
}

/** Server snapshot (never rendered on a server here, but required). */
function getServerSnapshot(): string | null {
  return null;
}

export interface AdminSession {
  /** Whether an admin token is present. Not whether it is still valid — the
   *  server decides that, and adminApi reports expiry by clearing it. */
  isSignedIn: boolean;
  /** Clear the token and re-render every subscribed section. */
  signOut: () => void;
}

export function useAdminSession(): AdminSession {
  const token = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const signOut = useCallback(() => {
    clearAdminToken();
    notifyAdminSessionChanged();
  }, []);

  return { isSignedIn: token !== null, signOut };
}
