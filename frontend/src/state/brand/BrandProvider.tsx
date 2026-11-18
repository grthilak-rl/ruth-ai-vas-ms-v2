/**
 * The active product brand (white-label) for every screen.
 *
 * Read from the open GET /api/v1/branding, so the sign-in page has it too.
 * Applies what belongs to the document — tab title, favicon, accent colour —
 * and hands names and logos to components through useBrand().
 *
 * Until the first answer arrives, `ready` is false and the header shows no
 * logo, so a RuthLabs demo never flashes the Visics logo. If the server
 * cannot be reached, the Visics files built into the app are used: the UI is
 * never left without a brand. A brand switch reaches open screens within a
 * minute (and at once on window focus).
 */

import { useEffect, useMemo, useRef, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getActiveBrand } from '../api/branding.api';
import {
  ACTIVE_BRAND_QUERY_KEY,
  BLANK_ICON,
  BrandContext,
  FALLBACK_BRAND,
  INITIAL_TITLE,
  LOADING_BRAND,
  toBrand,
  type Brand,
} from './brand';

function setIconLinks(href: string): void {
  for (const rel of ['icon', 'apple-touch-icon']) {
    let link = document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);
    if (!link) {
      link = document.createElement('link');
      link.rel = rel;
      document.head.appendChild(link);
    }
    if (link.getAttribute('href') !== href) link.href = href;
  }
}

export function BrandProvider({ children }: { children: ReactNode }) {
  const query = useQuery({
    queryKey: ACTIVE_BRAND_QUERY_KEY,
    queryFn: getActiveBrand,
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    retry: 1,
  });

  const brand = useMemo<Brand>(() => {
    if (query.data) return toBrand(query.data);
    if (query.isError) return FALLBACK_BRAND;
    return LOADING_BRAND;
  }, [query.data, query.isError]);

  // Tab title: only while it is ours (initial or the last product name we
  // set), so a page with its own title (the fullscreen camera) keeps it.
  const lastTitle = useRef<string>(INITIAL_TITLE);
  useEffect(() => {
    if (!brand.ready) return;
    if (document.title === lastTitle.current || document.title === INITIAL_TITLE) {
      document.title = brand.productName;
    }
    lastTitle.current = brand.productName;
  }, [brand.ready, brand.productName]);

  useEffect(() => {
    if (!brand.ready) return;
    setIconLinks(brand.icon ?? BLANK_ICON);
  }, [brand.ready, brand.icon]);

  useEffect(() => {
    const root = document.documentElement;
    if (brand.accent) root.style.setProperty('--brand-accent', brand.accent);
    else root.style.removeProperty('--brand-accent');
  }, [brand.accent]);

  return <BrandContext.Provider value={brand}>{children}</BrandContext.Provider>;
}
