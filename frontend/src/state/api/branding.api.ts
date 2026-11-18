/**
 * Product (white-label) branding: whose product this is.
 *
 * Not the customer branding on report covers (customerReports.ts). The
 * active brand is open (the sign-in page shows it); profiles and switching
 * are admin-only, under Settings -> System.
 */

import { ADMIN_API_PREFIX, adminFetch, getAdminToken } from '../../pages/admin/adminApi';
import { buildApiUrl } from '../../config/api';

/** GET /api/v1/branding: the active brand, as anyone may see it. */
export interface ActiveBrand {
  product_name: string;
  short_name: string;
  assistant_name: string;
  accent: string | null;
  /** Versioned URLs, or null when the brand has no such image. */
  logo_light: string | null;
  logo_dark: string | null;
  icon: string | null;
}

export type BrandImageSlot = 'logo_light' | 'logo_dark' | 'icon';
export const BRAND_IMAGE_SLOTS: BrandImageSlot[] = ['logo_light', 'logo_dark', 'icon'];

export interface BrandProfile {
  id: string;
  name: string;
  product_name: string;
  short_name: string | null;
  assistant_name: string | null;
  accent: string | null;
  report_note: string | null;
  /** slot -> version when set, else null. */
  images: Record<BrandImageSlot, string | null>;
  builtin_images: BrandImageSlot[];
  active: boolean;
}

export interface ProductBranding {
  active_id: string;
  profiles: BrandProfile[];
  updated_by: string | null;
  updated_at: string | null;
}

export interface BrandFields {
  name: string;
  product_name: string;
  short_name: string | null;
  assistant_name: string | null;
  accent: string | null;
  report_note: string | null;
}

export const MAX_BRAND_IMAGE_BYTES = 1024 * 1024;

/** WCAG contrast of a #rrggbb colour against white (the server checks the same: 3:1). */
export function contrastOnWhite(hex: string): number {
  const channel = (i: number) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
  return 1.05 / (luminance + 0.05);
}

const ADMIN = `${ADMIN_API_PREFIX}/product-branding`;

export async function getActiveBrand(): Promise<ActiveBrand> {
  const response = await fetch(buildApiUrl('/api/v1/branding'), { cache: 'no-cache' });
  if (!response.ok) throw new Error(`branding: HTTP ${response.status}`);
  return (await response.json()) as ActiveBrand;
}

/** Image URLs from the API are paths; make them absolute for the base URL. */
export function brandAssetUrl(path: string | null): string | null {
  return path ? buildApiUrl(path) : null;
}

export function getProductBranding(): Promise<ProductBranding> {
  return adminFetch<ProductBranding>(ADMIN);
}

export function createBrandProfile(fields: BrandFields): Promise<ProductBranding> {
  return adminFetch<ProductBranding>(`${ADMIN}/profiles`, {
    method: 'POST',
    body: JSON.stringify(fields),
  });
}

export function updateBrandProfile(id: string, fields: BrandFields): Promise<ProductBranding> {
  return adminFetch<ProductBranding>(`${ADMIN}/profiles/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(fields),
  });
}

export function deleteBrandProfile(id: string): Promise<ProductBranding> {
  return adminFetch<ProductBranding>(`${ADMIN}/profiles/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function activateBrandProfile(id: string): Promise<ProductBranding> {
  return adminFetch<ProductBranding>(`${ADMIN}/profiles/${encodeURIComponent(id)}/activate`, {
    method: 'POST',
  });
}

/** The image is the request body: one file, no form fields. */
export function uploadBrandImage(id: string, slot: BrandImageSlot, file: File): Promise<ProductBranding> {
  return adminFetch<ProductBranding>(
    `${ADMIN}/profiles/${encodeURIComponent(id)}/images/${slot}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    }
  );
}

export function deleteBrandImage(id: string, slot: BrandImageSlot): Promise<ProductBranding> {
  return adminFetch<ProductBranding>(
    `${ADMIN}/profiles/${encodeURIComponent(id)}/images/${slot}`,
    { method: 'DELETE' }
  );
}

/** The admin image endpoint needs the admin header, so previews are blob URLs. */
export async function fetchBrandImageUrl(id: string, slot: BrandImageSlot): Promise<string | null> {
  const token = getAdminToken();
  if (!token) return null;
  const response = await fetch(
    buildApiUrl(`${ADMIN}/profiles/${encodeURIComponent(id)}/images/${slot}`),
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) return null;
  return URL.createObjectURL(await response.blob());
}
