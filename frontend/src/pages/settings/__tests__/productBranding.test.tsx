// @vitest-environment jsdom
/**
 * Settings -> System -> Branding: profiles listed with the active one
 * marked; switching asks first, then every screen re-reads the brand; the
 * active profile cannot be deleted; signed out, the card only says which
 * brand is active.
 */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProductBranding } from '../../../state/api/branding.api';

const api = vi.hoisted(() => ({
  getProductBranding: vi.fn(),
  activateBrandProfile: vi.fn(),
  fetchBrandImageUrl: vi.fn(async () => null),
}));
vi.mock('../../../state/api/branding.api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../state/api/branding.api')>()),
  ...api,
}));

const session = vi.hoisted(() => ({ isSignedIn: true }));
vi.mock('../../admin/useAdminSession', () => ({ useAdminSession: () => session }));
vi.mock('react-router-dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router-dom')>()),
  useOutletContext: () => ({ sessionExpired: false }),
}));
vi.mock('../InlineAdminSignIn', () => ({ InlineAdminSignIn: () => <form data-signin /> }));

const { ProductBrandingCard } = await import('../ProductBrandingCard');

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function state(activeId: string): ProductBranding {
  const profile = (id: string, name: string, product: string) => ({
    id, name, product_name: product, short_name: null, assistant_name: null, accent: null,
    report_note: null, images: { logo_light: null, logo_dark: null, icon: null },
    builtin_images: [], active: id === activeId,
  });
  return {
    active_id: activeId,
    profiles: [profile('visics', 'Visics', 'Visics AI'), profile('p-1', 'RuthLabs', 'Ruth AI')],
    updated_by: 'admin', updated_at: '2026-11-18T10:00:00Z',
  };
}

let root: Root | null = null;
let container: HTMLDivElement;
let client: QueryClient;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  session.isSignedIn = true;
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container.remove();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

async function render() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root = createRoot(container);
    root.render(
      <QueryClientProvider client={client}>
        <ProductBrandingCard />
      </QueryClientProvider>
    );
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

const items = () => Array.from(container.querySelectorAll('.product-branding__item'));
const button = (item: Element, label: string) =>
  Array.from(item.querySelectorAll('button')).find((b) => b.textContent === label) as HTMLButtonElement | undefined;

describe('ProductBrandingCard', () => {
  it('lists profiles; the active one is marked and cannot be deleted', async () => {
    api.getProductBranding.mockResolvedValue(state('visics'));
    await render();
    const [visics, ruth] = items();
    expect(visics.textContent).toContain('Active');
    expect(button(visics, 'Activate')).toBeUndefined();
    expect(button(visics, 'Delete')?.disabled).toBe(true);
    expect(button(ruth, 'Activate')).toBeDefined();
    expect(button(ruth, 'Delete')?.disabled).toBe(false);
  });

  it('switching asks first, then refreshes the active brand everywhere', async () => {
    api.getProductBranding.mockResolvedValue(state('visics'));
    api.activateBrandProfile.mockResolvedValue(state('p-1'));
    await render();
    const invalidate = vi.spyOn(client, 'invalidateQueries');

    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false);
    await act(async () => button(items()[1], 'Activate')!.click());
    expect(confirm.mock.calls[0][0]).toContain('Ruth AI');
    expect(api.activateBrandProfile).not.toHaveBeenCalled();

    confirm.mockReturnValueOnce(true);
    await act(async () => button(items()[1], 'Activate')!.click());
    expect(api.activateBrandProfile).toHaveBeenCalledWith('p-1');
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['active-brand'] });
    expect(items()[1].textContent).toContain('Active');
  });

  it('signed out: says which brand is active and offers sign-in, nothing else', async () => {
    session.isSignedIn = false;
    await render();
    expect(container.textContent).toContain('Active now');
    expect(container.querySelector('[data-signin]')).not.toBeNull();
    expect(api.getProductBranding).not.toHaveBeenCalled();
  });
});
