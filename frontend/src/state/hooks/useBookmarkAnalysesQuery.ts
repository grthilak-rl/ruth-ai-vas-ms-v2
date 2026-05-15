/**
 * Bookmark Analyses query/mutation hooks.
 *
 * The detail hook polls only while the analysis is still in flight.
 * Completed and failed analyses are immutable so we stop polling once
 * we observe a terminal state — saves a network call every 5 seconds
 * for the (typical) case of a long-since-finished row.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../queryKeys';
import { POLLING_INTERVALS } from '../pollingIntervals';
import {
  getBookmarkAnalysis,
  listAnalysesForBookmark,
  listBookmarkAnalyses,
  submitBookmarkAnalysis,
  type BookmarkAnalysis,
  type BookmarkAnalysisListItem,
  type BookmarkAnalysisListResponse,
  type BookmarkAnalysisSubmitRequest,
} from '../api/bookmarkAnalyses.api';

export function useBookmarkAnalysesListQuery(limit = 50) {
  return useQuery({
    queryKey: queryKeys.bookmarkAnalyses.list(limit),
    queryFn: () => listBookmarkAnalyses(limit),
    refetchInterval: POLLING_INTERVALS.ANALYSIS_LIST,
    staleTime: POLLING_INTERVALS.ANALYSIS_LIST / 2,
    refetchIntervalInBackground: false,
  });
}

export function useAnalysesForBookmarkQuery(
  vasBookmarkId: string | null | undefined,
) {
  return useQuery({
    queryKey: queryKeys.bookmarkAnalyses.forBookmark(vasBookmarkId ?? ''),
    queryFn: () => listAnalysesForBookmark(vasBookmarkId as string),
    enabled: !!vasBookmarkId,
    staleTime: POLLING_INTERVALS.ANALYSIS_LIST / 2,
  });
}

export function useBookmarkAnalysisQuery(id: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.bookmarkAnalyses.detail(id ?? ''),
    queryFn: () => getBookmarkAnalysis(id as string),
    enabled: !!id,
    refetchInterval: (query) => {
      const data = query.state.data as BookmarkAnalysis | undefined;
      // Keep polling while the worker is still working. Stop once we
      // see a terminal state — completed/failed rows never change.
      if (!data) return POLLING_INTERVALS.ANALYSIS_DETAIL_RUNNING;
      return data.state === 'pending' || data.state === 'running'
        ? POLLING_INTERVALS.ANALYSIS_DETAIL_RUNNING
        : false;
    },
    refetchIntervalInBackground: false,
  });
}

export function useSubmitBookmarkAnalysisMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: BookmarkAnalysisSubmitRequest) =>
      submitBookmarkAnalysis(request),
    onSuccess: (created) => {
      // Surface the new row immediately on the list page + per-bookmark
      // subresource (the detail page will fetch on mount via its own hook).
      queryClient.invalidateQueries({
        queryKey: queryKeys.bookmarkAnalyses.all,
      });
      // Pre-seed the detail cache so the navigation to the new analysis
      // doesn't flash a loading state.
      queryClient.setQueryData(
        queryKeys.bookmarkAnalyses.detail(created.id),
        created,
      );
    },
  });
}

export type {
  BookmarkAnalysis,
  BookmarkAnalysisListItem,
  BookmarkAnalysisListResponse,
  BookmarkAnalysisSubmitRequest,
};
