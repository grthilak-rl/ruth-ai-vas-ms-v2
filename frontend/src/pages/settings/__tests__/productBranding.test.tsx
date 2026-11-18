// @vitest-environment jsdom
/**
 * Settings -> System -> Branding: profiles listed with the active one
 * marked; switching asks first, then every screen re-reads the brand; the
 * active profile cannot be deleted; signed out, the card only says which
 * brand is active. The thumbnail falls back icon -> light logo -> initials.
 * One form, one Save: chosen images are pending until Save, then saved with
 * the profile, and the form closes.
 */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProductBranding } from '../../../state/api/branding.api';

const api = vi.hoisted(() => ({
  getProductBranding: vi.fn(),
  activateBrandProfile: vi.fn(),
  createBrandProfile: vi.fn(),
  updateBrandProfile: vi.fn(),
  uploadBrandImage: vi.fn(),
  deleteBrandImage: vi.fn(),
  fetchBrandImageUrl: vi.fn<(id: string, slot: string) => Promise<string | null>>(async () => null),
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
const { checkBrandImage, profileInitials, thumbSlot } = await import('../productBrandingRules');

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Images = ProductBranding['profiles'][number]['images'];
const NO_IMAGES: Images = { logo_light: null, logo_dark: null, icon: null };

function state(activeId: string, ruthImages: Partial<Images> = {}, extra: string[] = []): ProductBranding {
  const profile = (id: string, name: string, product: string, images: Partial<Images> = {}) => ({
    id, name, product_name: product, short_name: null, assistant_name: null, accent: null,
    report_note: null, images: { ...NO_IMAGES, ...images },
    builtin_images: [], active: id === activeId,
  });
  return {
    active_id: activeId,
    profiles: [
      profile('visics', 'Visics', 'Visics AI'),
      profile('p-1', 'RuthLabs', 'Ruth AI', ruthImages),
      ...extra.map((id) => profile(id, 'ACME', 'ACME Vision', { logo_light: 'v-acme' })),
    ],
    updated_by: 'admin', updated_at: '2026-11-18T10:00:00Z',
  };
}

let root: Root | null = null;
let container: HTMLDivElement;
let client: QueryClient;

beforeEach(() => {
  // jsdom has no object URLs.
  let n = 0;
  URL.createObjectURL = vi.fn(() => `blob:chosen-${++n}`);
  URL.revokeObjectURL = vi.fn();
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

const settle = () => act(async () => {
  await new Promise((r) => setTimeout(r, 0));
});

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

// --- helpers for the form ----------------------------------------------------

const form = () => container.querySelector('form.product-branding__form') as HTMLFormElement | null;
const formButton = (label: string) =>
  Array.from(form()!.querySelectorAll('button')).find((b) => b.textContent === label) as HTMLButtonElement | undefined;
const slot = (name: string) => form()!.querySelector(`[data-slot="${name}"]`) as HTMLElement;
const slotButton = (name: string, label: string) =>
  Array.from(slot(name).querySelectorAll('button')).find((b) => b.textContent === label) as HTMLButtonElement | undefined;

function type(labelStart: string, value: string) {
  const label = Array.from(form()!.querySelectorAll('label')).find((l) =>
    l.textContent?.startsWith(labelStart)
  )!;
  const input = label.querySelector('input')!;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function choose(slotName: string, file: File) {
  const input = slot(slotName).querySelector('input[type="file"]') as HTMLInputElement;
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  await act(async () => {
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await settle();
}

const png = (name = 'logo.png', size = 2000) => new File([new Uint8Array(size)], name, { type: 'image/png' });

async function submit() {
  await act(async () => {
    form()!.requestSubmit();
  });
  await settle();
}

describe('profile thumbnail', () => {
  it('picks the icon, else the light logo, else initials', () => {
    expect(thumbSlot({ images: { ...NO_IMAGES, icon: 'a', logo_light: 'b' } })).toBe('icon');
    expect(thumbSlot({ images: { ...NO_IMAGES, logo_light: 'b' } })).toBe('logo_light');
    expect(thumbSlot({ images: { ...NO_IMAGES, logo_dark: 'c' } })).toBeNull();
    expect(profileInitials({ name: 'RuthLabs', product_name: 'Ruth AI' })).toBe('RA');
    expect(profileInitials({ name: 'X', product_name: 'acme' })).toBe('A');
  });

  it('shows the light logo when there is no icon, and initials when there is neither', async () => {
    api.getProductBranding.mockResolvedValue(state('visics', { logo_light: 'v1' }));
    api.fetchBrandImageUrl.mockImplementation(async (id, s) => `blob:${id}-${s}`);
    await render();
    const [visics, ruth] = items();
    expect(visics.querySelector('img')).toBeNull();
    expect(visics.querySelector('.product-branding__thumb--initials')?.textContent).toBe('VA');
    expect(ruth.querySelector('img')?.getAttribute('src')).toBe('blob:p-1-logo_light');
    expect(ruth.querySelector('.product-branding__empty')).toBeNull();
  });

  it('switches to the icon right after the icon is saved', async () => {
    api.getProductBranding.mockResolvedValue(state('visics', { logo_light: 'v1' }));
    api.fetchBrandImageUrl.mockImplementation(async (id, s) => `blob:${id}-${s}`);
    api.updateBrandProfile.mockResolvedValue(state('visics', { logo_light: 'v1' }));
    api.uploadBrandImage.mockResolvedValue(state('visics', { logo_light: 'v1', icon: 'v2' }));
    await render();
    await act(async () => button(items()[1], 'Edit')!.click());
    await choose('icon', png('icon.png'));
    await submit();
    expect(items()[1].querySelector('img')?.getAttribute('src')).toBe('blob:p-1-icon');
  });
});

describe('one form, one save', () => {
  it('add: images chosen in the same form are pending, then saved with the profile, and the form closes', async () => {
    api.getProductBranding.mockResolvedValue(state('visics'));
    api.createBrandProfile.mockResolvedValue(state('visics', {}, ['p-2']));
    api.uploadBrandImage.mockResolvedValue(state('visics', {}, ['p-2']));
    await render();

    await act(async () => button(container, 'Add profile')!.click());
    expect(form()).not.toBeNull();
    type('Label', 'ACME');
    type('Product name', 'ACME Vision');
    const logo = png();
    await choose('logo_light', logo);

    // Pending, nothing sent yet; Replace and Remove per slot.
    expect(slot('logo_light').textContent).toContain('Will be saved');
    expect(slot('logo_light').querySelector('img')?.getAttribute('src')).toMatch(/^blob:chosen-/);
    expect(slotButton('logo_light', 'Replace')).toBeDefined();
    expect(slotButton('logo_light', 'Remove')).toBeDefined();
    expect(form()!.textContent).toContain('1 image change not saved yet');
    expect(api.createBrandProfile).not.toHaveBeenCalled();
    expect(api.uploadBrandImage).not.toHaveBeenCalled();

    // The only Save is the last button row, after the image slots.
    const buttons = Array.from(form()!.querySelectorAll('button[type="submit"]'));
    expect(buttons.map((b) => b.textContent)).toEqual(['Add profile']);
    const images = form()!.querySelector('.product-branding__images')!;
    expect(images.compareDocumentPosition(buttons[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await submit();
    expect(api.createBrandProfile).toHaveBeenCalledTimes(1);
    expect(api.createBrandProfile.mock.calls[0][0]).toMatchObject({ name: 'ACME', product_name: 'ACME Vision' });
    expect(api.uploadBrandImage).toHaveBeenCalledWith('p-2', 'logo_light', logo);
    expect(api.createBrandProfile.mock.invocationCallOrder[0]).toBeLessThan(
      api.uploadBrandImage.mock.invocationCallOrder[0]
    );
    // Closed, not left open as an empty "New brand profile".
    expect(form()).toBeNull();
    expect(container.querySelector('[role="status"]')?.textContent).toBe('Added “ACME” with 1 image change.');
    expect(button(container, 'Add profile')).toBeDefined();
  });

  it('edit: Remove is pending until Save; Save sends the text and the removal, then closes', async () => {
    api.getProductBranding.mockResolvedValue(state('visics', { logo_light: 'v1' }));
    api.fetchBrandImageUrl.mockImplementation(async (id, s) => `blob:${id}-${s}`);
    api.updateBrandProfile.mockResolvedValue(state('visics', { logo_light: 'v1' }));
    api.deleteBrandImage.mockResolvedValue(state('visics'));
    await render();
    await act(async () => button(items()[1], 'Edit')!.click());
    expect(slot('logo_light').textContent).toContain('Saved');

    await act(async () => slotButton('logo_light', 'Remove')!.click());
    expect(slot('logo_light').textContent).toContain('Will be removed');
    expect(api.deleteBrandImage).not.toHaveBeenCalled();
    // Undo puts it back.
    await act(async () => slotButton('logo_light', 'Undo')!.click());
    expect(slot('logo_light').textContent).toContain('Saved');
    await act(async () => slotButton('logo_light', 'Remove')!.click());

    type('Product name', 'Ruth AI Demo');
    await submit();
    expect(api.updateBrandProfile.mock.calls[0]).toEqual(['p-1', expect.objectContaining({ product_name: 'Ruth AI Demo' })]);
    expect(api.deleteBrandImage).toHaveBeenCalledWith('p-1', 'logo_light');
    expect(form()).toBeNull();
    expect(container.querySelector('[role="status"]')?.textContent).toBe('Saved “RuthLabs” with 1 image change.');
  });

  it('a refused image keeps the form open with it pending; Save again saves, it does not add twice', async () => {
    api.getProductBranding.mockResolvedValue(state('visics'));
    api.createBrandProfile.mockResolvedValue(state('visics', {}, ['p-2']));
    api.updateBrandProfile.mockResolvedValue(state('visics', {}, ['p-2']));
    api.uploadBrandImage
      .mockRejectedValueOnce(new Error('The icon must be square (or nearly).'))
      .mockResolvedValueOnce(state('visics', {}, ['p-2']));
    await render();
    await act(async () => button(container, 'Add profile')!.click());
    type('Label', 'ACME');
    type('Product name', 'ACME Vision');
    await choose('icon', png('icon.png'));
    await submit();

    expect(form()).not.toBeNull();
    expect(form()!.querySelector('[role="alert"]')?.textContent).toContain('“ACME” is saved, but the icon (browser tab) is not');
    expect(slot('icon').textContent).toContain('Will be saved');
    expect(formButton('Save')).toBeDefined();

    await submit();
    expect(api.createBrandProfile).toHaveBeenCalledTimes(1);
    expect(api.updateBrandProfile).toHaveBeenCalledWith('p-2', expect.anything());
    expect(api.uploadBrandImage).toHaveBeenCalledTimes(2);
    expect(form()).toBeNull();
  });

  it('a wrong file is refused when chosen, not queued', async () => {
    api.getProductBranding.mockResolvedValue(state('visics'));
    await render();
    await act(async () => button(container, 'Add profile')!.click());
    await choose('logo_light', new File(['<svg/>'], 'logo.svg', { type: 'image/svg+xml' }));
    expect(form()!.querySelector('[role="alert"]')?.textContent).toContain('PNG or JPEG');
    expect(slot('logo_light').textContent).not.toContain('Will be saved');
  });
});

describe('checkBrandImage', () => {
  afterEach(() => {
    delete (globalThis as { createImageBitmap?: unknown }).createImageBitmap;
  });

  const bitmap = (width: number, height: number) => {
    (globalThis as { createImageBitmap?: unknown }).createImageBitmap = vi.fn(async () => ({
      width, height, close: () => {},
    }));
  };

  it('keeps the existing rules: PNG/JPEG, 1 MB, a (nearly) square icon', async () => {
    expect(await checkBrandImage('logo_light', new File(['x'], 'a.gif', { type: 'image/gif' }))).toContain('PNG or JPEG');
    expect(await checkBrandImage('logo_light', png('big.png', 1024 * 1024 + 1))).toContain('1 MB');
    expect(await checkBrandImage('logo_light', png())).toBeNull();
    bitmap(300, 100);
    expect(await checkBrandImage('logo_light', png())).toBeNull();
    expect(await checkBrandImage('icon', png())).toContain('300 × 100');
    bitmap(250, 200);
    expect(await checkBrandImage('icon', png())).toBeNull();
  });
});
