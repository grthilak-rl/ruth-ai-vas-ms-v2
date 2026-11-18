import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  fetchProjectJobs,
  isJobActive,
  retryProjectJob,
  type ProjectJob,
} from '../admin/adminApi';
import { projectQueryKeys } from '../../state/project/projectsApi';

export const PROJECT_JOBS_KEY = ['admin', 'project-jobs'] as const;
const POLL_MS = 1500;

/**
 * The project action (Start/Stop/End/Resume job) running now, and the last one.
 *
 * Polls every 1.5 s while a job is queued or running, and not at all
 * otherwise. When a job finishes, the project lists are refetched so the
 * tab shows the new state. `track` shows a job just queued at once, before
 * the first poll; `shown` is the job the tab should display: the running
 * one, else the last one if it needs attention (failed / interrupted) or was
 * started from this page, unless dismissed.
 */
export function useProjectJobs(enabled = true) {
  const queryClient = useQueryClient();
  const jobs = useQuery({
    queryKey: PROJECT_JOBS_KEY,
    queryFn: fetchProjectJobs,
    retry: false,
    enabled,
    refetchInterval: (query) => (isJobActive(query.state.data?.active) ? POLL_MS : false),
  });
  const [tracked, setTracked] = useState<ReadonlySet<string>>(() => new Set());
  const [dismissed, setDismissed] = useState<string | null>(null);

  const active = jobs.data?.active ?? null;
  const latest = jobs.data?.latest ?? null;

  // A job finished (it was active on the last poll, now it is not): the
  // project's state changed, so refetch the lists that show it.
  const wasActive = useRef<string | null>(null);
  useEffect(() => {
    const id = active?.id ?? null;
    if (wasActive.current && wasActive.current !== id) {
      queryClient.invalidateQueries({ queryKey: ['admin', 'projects'] });
      queryClient.invalidateQueries({ queryKey: projectQueryKeys.list });
    }
    wasActive.current = id;
  }, [active?.id, queryClient]);

  const track = useCallback(
    (job: ProjectJob) => {
      setTracked((prev) => new Set(prev).add(job.id));
      setDismissed(null);
      queryClient.setQueryData(PROJECT_JOBS_KEY, {
        active: isJobActive(job) ? job : null,
        latest: job,
      });
    },
    [queryClient]
  );

  const retry = useMutation({
    mutationFn: (id: string) => retryProjectJob(id),
    onSuccess: track,
  });

  let shown: ProjectJob | null = active;
  if (!shown && latest && latest.id !== dismissed) {
    const needsAttention = latest.state === 'failed' || latest.state === 'interrupted';
    if (needsAttention || tracked.has(latest.id)) shown = latest;
  }

  return {
    active,
    latest,
    shown,
    busy: isJobActive(active),
    track,
    retry,
    dismiss: (id: string) => setDismissed(id),
    error: jobs.error,
  };
}
