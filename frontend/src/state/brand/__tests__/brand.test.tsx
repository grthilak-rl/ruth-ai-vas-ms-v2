// @vitest-environment jsdom
/**
 * Product (white-label) brand in the UI:
 * - the provider applies the active brand to the tab title, favicon and
 *   accent, and never shows a logo before it knows the brand;
 * - if the server cannot be asked, the built-in Visics brand is used;
 * - a page with its own title (the fullscreen camera) keeps it;
 * - the sign-in page shows the active brand without a session.
 */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BrandProvider } from '../BrandProvider';
import { FALLBACK_BRAND, INITIAL_TITLE, useBrand } from '../brand';
import { contrastOnWhite } from '../../api/branding.api';
import { AdminLogin } from '../../../pages/admin/AdminLogin';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const RUTH = {
  product_name: 'Ruth AI',
  short_name: 'Ruth AI',
  assistant_name: 'Ruth',
  accent: '#184f95',
  logo_light: '/api/v1/branding/asset/logo_light?v=abc',
  logo_dark: null,
  icon: null,
};

let root: Root | null = null;
let container: HTMLDivElement;
const fetchMock = vi.fn();

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  document.title = INITIAL_TITLE;
  document.head.querySelectorAll('link[rel="icon"], link[rel="apple-touch-icon"]').forEach((l) => l.remove());
  document.documentElement.style.removeProperty('--brand-accent');
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container.remove();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

function respond(body: unknown, ok = true) {
  fetchMock.mockResolvedValue({ ok, status: ok ? 200 : 500, json: async () => body });
}

let seen: ReturnType<typeof useBrand>[] = [];
function Probe() {
  const brand = useBrand();
  seen.push(brand);
  return <span data-testid="probe">{brand.ready ? brand.productName : 'loading'}</span>;
}

async function render(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root = createRoot(container);
    root.render(
      <QueryClientProvider client={client}>
        <BrandProvider>{node}</BrandProvider>
      </QueryClientProvider>
    );
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

const icon = () => document.head.querySelector<HTMLLinkElement>('link[rel="icon"]');

describe('BrandProvider', () => {
  it('applies the active brand: title, logo, accent; no other brand icon', async () => {
    seen = [];
    respond(RUTH);
    await render(<Probe />);
    expect(seen[0].ready).toBe(false);
    expect(seen[0].logoLight).toBeNull(); // nothing to flash before the answer
    const brand = seen[seen.length - 1];
    expect(brand).toMatchObject({ ready: true, productName: 'Ruth AI', assistantName: 'Ruth' });
    expect(brand.logoLight).toBe(RUTH.logo_light);
    expect(brand.logoDark).toBe(RUTH.logo_light); // falls back to the light logo
    expect(document.title).toBe('Ruth AI');
    expect(document.documentElement.style.getPropertyValue('--brand-accent')).toBe('#184f95');
    // RuthLabs has no icon: a blank one, never the Visics eye.
    expect(icon()?.href).toMatch(/^data:image\/png/);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/branding', { cache: 'no-cache' });
  });

  it('falls back to the built-in Visics brand when the server cannot be asked', async () => {
    seen = [];
    respond({}, false);
    await render(<Probe />);
    // The provider retries once (about a second) before falling back.
    await act(async () => {
      await vi.waitFor(() => expect(seen[seen.length - 1].ready).toBe(true), { timeout: 4000 });
    });
    const brand = seen[seen.length - 1];
    expect(brand).toEqual(FALLBACK_BRAND);
    expect(document.title).toBe('Visics AI');
    expect(icon()?.getAttribute('href')).toBe('/visics_icon.png');
  });

  it('leaves a page title it did not set alone', async () => {
    respond(RUTH);
    document.title = 'Gate 3 - Ruth AI Live';
    await render(<Probe />);
    expect(document.title).toBe('Gate 3 - Ruth AI Live');
  });
});

describe('Admin sign-in page', () => {
  it('shows the active brand before anyone signs in', async () => {
    respond(RUTH);
    await render(
      <MemoryRouter>
        <AdminLogin />
      </MemoryRouter>
    );
    const logo = container.querySelector<HTMLImageElement>('.admin-login__logo');
    expect(logo?.getAttribute('src')).toBe(RUTH.logo_light);
    expect(logo?.alt).toBe('Ruth AI');
  });

  it('shows the product name when the brand has no logo', async () => {
    respond({ ...RUTH, logo_light: null });
    await render(
      <MemoryRouter>
        <AdminLogin />
      </MemoryRouter>
    );
    expect(container.querySelector('.admin-login__logo')).toBeNull();
    expect(container.querySelector('.admin-login__product')?.textContent).toBe('Ruth AI');
  });
});

describe('contrastOnWhite', () => {
  it('matches WCAG: black 21, white 1, the report blue above 3', () => {
    expect(contrastOnWhite('#000000')).toBeCloseTo(21, 0);
    expect(contrastOnWhite('#ffffff')).toBeCloseTo(1, 5);
    expect(contrastOnWhite('#2a78d6')).toBeGreaterThan(3);
    expect(contrastOnWhite('#ffff00')).toBeLessThan(3);
  });
});
