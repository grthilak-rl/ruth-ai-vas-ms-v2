import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Token expiry while the operator is sitting on Settings.
 *
 * This is the sharp edge of moving the admin pages into an open page. The
 * old behaviour — `window.location.replace('/admin/login')` on any 401 —
 * was fine when the whole page was admin content. On Settings it would
 * throw the operator off a page that still mostly works, losing the tab
 * they were on and anything typed into it.
 *
 * Three things have to hold, and each is a way this could go wrong:
 *
 *   1. With a handler registered (inside Settings), a 401 clears the token
 *      and notifies, and does NOT navigate.
 *   2. With no handler (the standalone login/detail pages), the redirect
 *      still happens — that path must not regress.
 *   3. No redirect loop: once the token is cleared, the next admin call
 *      fails fast on "no token" and still does not navigate. A loop here
 *      would be invisible in dev (fast redirect) and brutal in production.
 *
 * Runs in the default node environment — this project has no jsdom — so
 * the handful of browser globals the modules touch are stubbed. They are
 * stubbed, not mocked: the code under test is the real adminApi and the
 * real session store.
 */

const TOKEN_KEY = 'ruth_admin_token';

class MemoryStorage {
  private store = new Map<string, string>();
  getItem(key: string) {
    return this.store.has(key) ? this.store.get(key)! : null;
  }
  setItem(key: string, value: string) {
    this.store.set(key, value);
  }
  removeItem(key: string) {
    this.store.delete(key);
  }
  clear() {
    this.store.clear();
  }
}

let replaceCalls: string[];

beforeEach(() => {
  vi.resetModules();
  replaceCalls = [];

  vi.stubGlobal('sessionStorage', new MemoryStorage());
  vi.stubGlobal('window', {
    location: {
      pathname: '/settings/models',
      search: '',
      replace: (url: string) => replaceCalls.push(url),
    },
    addEventListener: () => {},
    removeEventListener: () => {},
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** A fetch that always answers 401, as an expired token would. */
function fetch401() {
  return vi.fn(async () =>
    new Response(JSON.stringify({ detail: { message: 'token expired' } }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    })
  );
}

describe('admin session expiry inside Settings', () => {
  it('clears the token, notifies, and does not navigate', async () => {
    const api = await import('../../admin/adminApi');
    vi.stubGlobal('fetch', fetch401());

    sessionStorage.setItem(TOKEN_KEY, 'stale-token');

    const onExpired = vi.fn();
    api.setSessionExpiredHandler(onExpired);

    await expect(api.listStoreModels()).rejects.toMatchObject({ status: 401 });

    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(onExpired).toHaveBeenCalledTimes(1);
    expect(replaceCalls).toEqual([]);
  });

  it('does not loop: the next call fails fast and still does not navigate', async () => {
    const api = await import('../../admin/adminApi');
    const doomedFetch = fetch401();
    vi.stubGlobal('fetch', doomedFetch);

    sessionStorage.setItem(TOKEN_KEY, 'stale-token');
    const onExpired = vi.fn();
    api.setSessionExpiredHandler(onExpired);

    // First call: real 401 from the server.
    await expect(api.listStoreModels()).rejects.toMatchObject({ status: 401 });
    expect(doomedFetch).toHaveBeenCalledTimes(1);

    // Second call, e.g. a react-query refetch racing the first. There is no
    // token now, so it must short-circuit rather than hit the server again
    // and re-enter the same handler forever.
    await expect(api.listStoreModels()).rejects.toMatchObject({ status: 401 });
    expect(doomedFetch).toHaveBeenCalledTimes(1);
    expect(replaceCalls).toEqual([]);
  });

  it('keeps redirecting when no handler is registered', async () => {
    const api = await import('../../admin/adminApi');
    vi.stubGlobal('fetch', fetch401());

    sessionStorage.setItem(TOKEN_KEY, 'stale-token');
    api.setSessionExpiredHandler(null);

    await expect(api.listStoreModels()).rejects.toMatchObject({ status: 401 });

    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(replaceCalls).toHaveLength(1);
    expect(replaceCalls[0]).toContain('/admin/login');
  });

  it('carries the Settings path into the login redirect', async () => {
    const api = await import('../../admin/adminApi');
    vi.stubGlobal('fetch', fetch401());

    // A tab other than the default landing one: adminLoginUrl omits a
    // redundant ?next= when the target already equals ADMIN_HOME_PATH, so
    // asserting from /settings/models would prove nothing.
    window.location.pathname = '/settings/project';

    sessionStorage.setItem(TOKEN_KEY, 'stale-token');
    api.setSessionExpiredHandler(null);

    await expect(api.listStoreModels()).rejects.toMatchObject({ status: 401 });

    // /settings/ is an allowed `next` target, so the operator returns to
    // where they were rather than the default landing tab.
    expect(replaceCalls[0]).toContain(encodeURIComponent('/settings/project'));
  });
});

describe('the admin session store', () => {
  it('notifies subscribers when the token changes', async () => {
    const { notifyAdminSessionChanged } = await import('../../admin/useAdminSession');
    const api = await import('../../admin/adminApi');

    // Subscribing is internal to the hook; what we can assert without a
    // renderer is that a 401 runs the handler Settings registers, which is
    // precisely the notify call.
    const notified = vi.fn();
    api.setSessionExpiredHandler(() => {
      notifyAdminSessionChanged();
      notified();
    });

    vi.stubGlobal('fetch', fetch401());
    sessionStorage.setItem(TOKEN_KEY, 'stale-token');

    await expect(api.listStoreModels()).rejects.toMatchObject({ status: 401 });
    expect(notified).toHaveBeenCalledTimes(1);
  });
});

describe('safeNextPath', () => {
  it('accepts the new Settings paths and the old admin ones', async () => {
    const { safeNextPath } = await import('../../admin/adminApi');
    expect(safeNextPath('/settings/project')).toBe('/settings/project');
    expect(safeNextPath('/admin/models')).toBe('/admin/models');
  });

  it('rejects off-site and protocol-relative targets', async () => {
    const { safeNextPath, ADMIN_HOME_PATH } = await import('../../admin/adminApi');
    expect(safeNextPath('//evil.example/settings/')).toBe(ADMIN_HOME_PATH);
    expect(safeNextPath('https://evil.example')).toBe(ADMIN_HOME_PATH);
    expect(safeNextPath('/alerts')).toBe(ADMIN_HOME_PATH);
    expect(safeNextPath(null)).toBe(ADMIN_HOME_PATH);
  });

  it('never bounces back to the login page itself', async () => {
    const { safeNextPath, ADMIN_HOME_PATH } = await import('../../admin/adminApi');
    expect(safeNextPath('/admin/login')).toBe(ADMIN_HOME_PATH);
  });

  it('lands on the AI Models tab by default', async () => {
    const { ADMIN_HOME_PATH } = await import('../../admin/adminApi');
    expect(ADMIN_HOME_PATH).toBe('/settings/models');
  });
});
