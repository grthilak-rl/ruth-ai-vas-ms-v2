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
    // Bookmarks are created by operator action (rare). One minute of
    // freshness is plenty for a picker dropdown.
    staleTime: 60 * 1000,
  });
}

export type { VasBookmark };
