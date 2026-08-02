import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '../queryKeys';
import { POLLING_INTERVALS } from '../pollingIntervals';
import {
  fetchCurrentShift,
  fetchCurrentShiftViolationCounts,
  fetchShiftSchedule,
  millisUntilShiftEnd,
  updateShiftSchedule,
} from '../api/shifts.api';
import type { ShiftSchedule } from '../api/shifts.api';

/**
 * Shift Schedule Query Hook
 *
 * The site-global schedule, as configured. Read-mostly: it changes only
 * when a supervisor edits it, so there is no polling — the mutation below
 * invalidates it.
 */
export function useShiftScheduleQuery() {
  return useQuery({
    queryKey: queryKeys.shifts.schedule,
    queryFn: fetchShiftSchedule,
    refetchInterval: false,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Shift Schedule Mutation Hook
 *
 * Rejects with a 422 ApiError when the proposed shifts overlap or leave
 * part of the day uncovered; the config UI surfaces `details.conflicts`.
 *
 * A successful write can change which shift is current and therefore
 * every card's count, so all three shift queries are invalidated.
 */
export function useUpdateShiftSchedule() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (schedule: ShiftSchedule & { updated_by?: string }) =>
      updateShiftSchedule(schedule),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.shifts.all });
    },
  });
}

/**
 * Current Shift Query Hook
 *
 * The shift window containing the server's current instant.
 *
 * Deliberately not polled. A shift boundary is known in advance — it is
 * the `end` of the window we already hold — so instead of asking the
 * backend every N seconds whether anything changed, this arms a single
 * timer for the moment it will. Between rollovers the request count is
 * zero; a twelve-hour shift costs two requests a day rather than
 * thousands.
 *
 * The small delay past `end` absorbs clock skew between browser and
 * server, so the refetch lands after the backend agrees the new shift has
 * started rather than a few milliseconds before it.
 */
const ROLLOVER_GRACE_MS = 2_000;

/**
 * setTimeout clamps delays above ~24.8 days, and a continuous 24h window
 * can be most of a day out. Re-arm in chunks instead of trusting one very
 * long timer.
 */
const MAX_TIMEOUT_MS = 6 * 60 * 60 * 1000;

export function useCurrentShiftQuery() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: queryKeys.shifts.current,
    queryFn: fetchCurrentShift,
    refetchInterval: false,
    // The window is valid until it ends; nothing else can invalidate it.
    staleTime: Infinity,
  });

  const endIso = query.data?.end;

  useEffect(() => {
    if (!endIso) return;

    const untilEnd = millisUntilShiftEnd(endIso);
    const delay = Math.min(untilEnd + ROLLOVER_GRACE_MS, MAX_TIMEOUT_MS);

    const timer = window.setTimeout(() => {
      // The new shift brings a new window and resets every card's count.
      queryClient.invalidateQueries({ queryKey: queryKeys.shifts.all });
    }, delay);

    return () => window.clearTimeout(timer);
  }, [endIso, queryClient]);

  return query;
}

/**
 * Current-Shift Violation Counts Query Hook
 *
 * One request per poll for the whole grid: pass every camera on screen and
 * the backend returns a zero-filled count for each.
 *
 * The response carries the shift window it was taken over, so the count and
 * the window on screen can never describe different shifts — which is the
 * failure mode of computing the window client-side and counting separately.
 *
 * @param cameraIds Cameras currently on the grid. Empty disables the query.
 */
export function useShiftViolationCountsQuery(cameraIds: string[]) {
  return useQuery({
    queryKey: queryKeys.shifts.violationCounts(cameraIds),
    queryFn: () => fetchCurrentShiftViolationCounts(cameraIds),
    enabled: cameraIds.length > 0,
    refetchInterval: POLLING_INTERVALS.SHIFT_VIOLATION_COUNTS,
    staleTime: POLLING_INTERVALS.SHIFT_VIOLATION_COUNTS / 2,
    refetchIntervalInBackground: false,
    // Keep the previous counts visible while a refetch is in flight so the
    // badges do not blink back to zero every 30 seconds.
    placeholderData: (previous) => previous,
  });
}
