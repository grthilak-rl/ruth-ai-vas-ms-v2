/**
 * Rules for Settings -> System -> Branding that the card and its tests share.
 * The server checks the same (product_branding.prepare_image); checking here
 * refuses a bad file when it is chosen rather than at Save.
 */

import { MAX_BRAND_IMAGE_BYTES, type BrandImageSlot, type BrandProfile } from '../../state/api/branding.api';

export const ACCEPTED_BRAND_IMAGE_TYPES = ['image/png', 'image/jpeg'];
/** Same as the server's ICON_MAX_ASPECT. */
export const ICON_MAX_ASPECT = 1.25;

/** "Ruth AI" -> "RA": the thumbnail when a profile has no icon or logo. */
export function profileInitials(p: Pick<BrandProfile, 'name' | 'product_name'>): string {
  const words = (p.product_name || p.name).trim().split(/\s+/).filter(Boolean);
  return words
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase();
}

/** Which image a profile's thumbnail shows: the icon, else the light logo, else none. */
export function thumbSlot(p: Pick<BrandProfile, 'images'>): BrandImageSlot | null {
  if (p.images.icon) return 'icon';
  if (p.images.logo_light) return 'logo_light';
  return null;
}

/**
 * Checks a chosen file: PNG or JPEG, 1 MB, and a (nearly) square icon.
 * Returns the problem, or null.
 */
export async function checkBrandImage(slot: BrandImageSlot, file: File): Promise<string | null> {
  if (!ACCEPTED_BRAND_IMAGE_TYPES.includes(file.type)) return 'Images must be PNG or JPEG.';
  if (file.size > MAX_BRAND_IMAGE_BYTES) return 'Images must be 1 MB or smaller.';
  if (slot === 'icon' && typeof createImageBitmap === 'function') {
    try {
      const bitmap = await createImageBitmap(file);
      const { width, height } = bitmap;
      bitmap.close();
      if (Math.max(width, height) / Math.max(1, Math.min(width, height)) > ICON_MAX_ASPECT) {
        return `The icon must be square (or nearly); this one is ${width} × ${height} px.`;
      }
    } catch {
      return 'This file could not be read as an image.';
    }
  }
  return null;
}
