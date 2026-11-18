/**
 * The active product brand: types, fallbacks and useBrand(). The provider
 * that loads it and applies it to the document is BrandProvider.tsx.
 */

import { createContext, useContext } from 'react';
import { brandAssetUrl, type ActiveBrand } from '../api/branding.api';

export interface Brand {
  productName: string;
  shortName: string;
  assistantName: string;
  accent: string | null;
  /** Logo for light backgrounds, or null to show the product name as text. */
  logoLight: string | null;
  /** Logo for dark backgrounds; falls back to the light one. */
  logoDark: string | null;
  icon: string | null;
  /** False until the brand is known (loaded, or fallen back after an error). */
  ready: boolean;
}

/** Shipped with the app; used only when the server cannot be asked. */
export const FALLBACK_BRAND: Brand = {
  productName: 'Visics AI',
  shortName: 'Visics AI',
  assistantName: 'Visi',
  accent: null,
  logoLight: '/visics_logo.jpeg',
  logoDark: '/visics_logo.jpeg',
  icon: '/visics_icon.png',
  ready: true,
};

export const LOADING_BRAND: Brand = { ...FALLBACK_BRAND, logoLight: null, logoDark: null, icon: null, ready: false };

/** The title in index.html, before any brand is known. */
export const INITIAL_TITLE = 'Video analytics';

/** A transparent favicon, for a brand that has no icon: better than another brand's. */
export const BLANK_ICON =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';

export const ACTIVE_BRAND_QUERY_KEY = ['active-brand'] as const;

export const BrandContext = createContext<Brand>(LOADING_BRAND);

export function toBrand(data: ActiveBrand): Brand {
  const logoLight = brandAssetUrl(data.logo_light);
  return {
    productName: data.product_name,
    shortName: data.short_name || data.product_name,
    assistantName: data.assistant_name || data.short_name || data.product_name,
    accent: data.accent,
    logoLight,
    logoDark: brandAssetUrl(data.logo_dark) ?? logoLight,
    icon: brandAssetUrl(data.icon),
    ready: true,
  };
}

export function useBrand(): Brand {
  return useContext(BrandContext);
}
