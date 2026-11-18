/**
 * The one place every request gets the viewed project: the fetch wrapper.
 * If this tags the wrong requests (or misses some), a past project's banner
 * could sit over the current project's numbers.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  PROJECT_HEADER,
  _resetForTests,
  getViewedProject,
  installProjectFetch,
  isRuthApi,
  projectFromSearch,
  setViewedProject,
  withProject,
} from '../viewProject';

function fakeWindow(search = '', pathname = '/alerts') {
  const calls: { url: string; headers: Headers }[] = [];
  const win = {
    location: { search, pathname, origin: 'http://portal.local' },
    fetch: vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      calls.push({ url, headers: new Headers(init?.headers) });
      return new Response('{}');
    }),
  };
  return { win: win as unknown as Window & typeof globalThis, calls };
}

afterEach(() => _resetForTests());

describe('installProjectFetch', () => {
  it('reads the initial project from the page URL', () => {
    const { win } = fakeWindow('?status=open&project=hpcl');
    installProjectFetch(win);
    expect(getViewedProject()).toBe('hpcl');
  });

  it('tags Ruth API requests only while a past project is open', async () => {
    const { win, calls } = fakeWindow('');
    installProjectFetch(win);
    await win.fetch('/api/v1/violations');
    setViewedProject('hpcl');
    await win.fetch('/api/v1/violations?limit=10');
    await win.fetch('http://portal.local/api/v1/admin/customer-reports', { method: 'POST' });
    await win.fetch('/v2/streams/1');
    await win.fetch('http://elsewhere.example/api/v1/violations');
    expect(calls.map((c) => c.headers.get(PROJECT_HEADER))).toEqual([null, 'hpcl', 'hpcl', null, null]);
  });

  it('keeps the caller\'s headers and never overrides an explicit project', async () => {
    const { win, calls } = fakeWindow('?project=hpcl');
    installProjectFetch(win);
    await win.fetch('/api/v1/violations', { headers: { Authorization: 'Bearer t' } });
    await win.fetch('/api/v1/violations', { headers: { [PROJECT_HEADER]: 'initial-data' } });
    expect(calls[0].headers.get('Authorization')).toBe('Bearer t');
    expect(calls[0].headers.get(PROJECT_HEADER)).toBe('hpcl');
    expect(calls[1].headers.get(PROJECT_HEADER)).toBe('initial-data');
  });

  it('never tags requests made from a live page', async () => {
    const { win, calls } = fakeWindow('?project=hpcl', '/cameras');
    installProjectFetch(win);
    await win.fetch('/api/v1/violations/counts/current-shift');
    expect(calls[0].headers.get(PROJECT_HEADER)).toBeNull();
  });

  it('stops tagging after Back to current project', async () => {
    const { win, calls } = fakeWindow('?project=hpcl');
    installProjectFetch(win);
    setViewedProject(null);
    await win.fetch('/api/v1/violations');
    expect(calls[0].headers.get(PROJECT_HEADER)).toBeNull();
  });
});

describe('URL helpers', () => {
  it('reads and writes the project param, keeping other params', () => {
    expect(projectFromSearch('?project=hpcl&status=open')).toBe('hpcl');
    expect(projectFromSearch('?project=')).toBeNull();
    expect(withProject('?status=open', 'hpcl')).toBe('?status=open&project=hpcl');
    expect(withProject('?status=open&project=hpcl', null)).toBe('?status=open');
    expect(withProject('', null)).toBe('');
  });

  it('recognises Ruth API URLs on the same origin only', () => {
    const origin = 'http://portal.local';
    expect(isRuthApi('/api/v1/violations', origin)).toBe(true);
    expect(isRuthApi('/api/v10/x', origin)).toBe(false);
    expect(isRuthApi('/v2/streams', origin)).toBe(false);
    expect(isRuthApi('https://other.example/api/v1/violations', origin)).toBe(false);
  });
});
