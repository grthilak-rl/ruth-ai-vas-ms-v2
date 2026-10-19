import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  alertsListPath,
  getStoredPageSize,
  readScrollPosition,
  rememberListSearch,
  saveScrollPosition,
  storePageSize,
} from '../alertsListMemory';

class MemoryStorage {
  private data = new Map<string, string>();
  getItem(k: string) {
    return this.data.has(k) ? this.data.get(k)! : null;
  }
  setItem(k: string, v: string) {
    this.data.set(k, String(v));
  }
}

beforeEach(() => {
  vi.stubGlobal('localStorage', new MemoryStorage());
  vi.stubGlobal('sessionStorage', new MemoryStorage());
});
afterEach(() => vi.unstubAllGlobals());

describe('alerts list memory', () => {
  it('remembers the page size per browser, within the allowed sizes', () => {
    expect(getStoredPageSize(10, [10, 25, 50])).toBe(10);
    storePageSize(25);
    expect(getStoredPageSize(10, [10, 25, 50])).toBe(25);
    storePageSize(7);
    expect(getStoredPageSize(10, [10, 25, 50])).toBe(10);
  });

  it('"Back to Alerts" returns to the last list URL', () => {
    expect(alertsListPath()).toBe('/alerts');
    rememberListSearch('range=30d&page=3');
    expect(alertsListPath()).toBe('/alerts?range=30d&page=3');
    rememberListSearch('');
    expect(alertsListPath()).toBe('/alerts');
  });

  it('keeps a scroll position per list URL, bounded', () => {
    saveScrollPosition('page=2', 840.6);
    expect(readScrollPosition('page=2')).toBe(841);
    expect(readScrollPosition('page=3')).toBe(0);
    for (let i = 0; i < 30; i++) saveScrollPosition(`p=${i}`, i);
    expect(readScrollPosition('page=2')).toBe(0); // evicted, oldest first
    expect(readScrollPosition('p=29')).toBe(29);
  });

  it('degrades to defaults when storage throws', () => {
    const boom = { getItem: () => { throw new Error('denied'); }, setItem: () => { throw new Error('denied'); } };
    vi.stubGlobal('localStorage', boom);
    vi.stubGlobal('sessionStorage', boom);
    expect(getStoredPageSize(10, [10])).toBe(10);
    expect(alertsListPath()).toBe('/alerts');
    expect(() => {
      storePageSize(25);
      rememberListSearch('x');
      saveScrollPosition('x', 5);
    }).not.toThrow();
    expect(readScrollPosition('x')).toBe(0);
  });
});
