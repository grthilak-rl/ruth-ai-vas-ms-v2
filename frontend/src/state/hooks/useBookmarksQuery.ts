/**
 * VAS bookmark hooks.
 *
 * Bookmarks are sourced from VAS directly (via the authenticated /v2
 * proxy). They change slowly so we keep them in cache for a minute.
 */

import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../queryKeys';
import { listBookmarks, type VasBookmark } from '../../services/api';

export function useBookmarksListQuery(limit = 50) {
  return useQuery({
    queryKey: queryKeys.bookmarks.list,
    queryFn: () => listBookmarks(limit),
    // Bookmarks are operator-created and change rarely; 5 minutes
    // of freshness is plenty for a picker dropdown. This keeps
    // navigating back to the page within 5 minutes instant — no
    // refetch on remount.
    staleTime: 5 * 60 * 1000,
  });
}

export type { VasBookmark };
