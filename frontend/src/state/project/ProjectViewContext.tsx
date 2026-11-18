import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocation, useNavigate } from 'react-router-dom';
import { fetchProjects, projectQueryKeys } from './projectsApi';
import { ProjectViewContext as Context, type ProjectView } from './projectView';
import {
  getViewedProject,
  projectFromSearch,
  setViewedProject,
  subscribeViewedProject,
  withProject,
} from './viewProject';

/**
 * Project view mode for the whole portal (see viewProject.ts for the wire
 * side). Mounted inside the router, in AppShell.
 *
 * - `?project=<slug>` in the URL selects a past project; links and refreshes
 *   keep it. In-app links do not carry it, so after a navigation the param
 *   is put back (replace, no history entry) while a past project is open.
 * - Naming the current project, or "Back to current project", clears it.
 * - Switching resets the query cache, so no screen ever shows one project's
 *   numbers under another project's banner.
 */

export function ProjectViewProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const viewedSlug = useSyncExternalStore(subscribeViewedProject, getViewedProject, getViewedProject);

  const list = useQuery({
    queryKey: projectQueryKeys.list,
    queryFn: fetchProjects,
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
  const projects = useMemo(() => list.data?.items ?? [], [list.data]);
  const current = list.data?.current ?? null;

  const switchTo = useCallback(
    (slug: string | null) => {
      if (slug === getViewedProject()) return;
      setViewedProject(slug);
      // Everything cached belongs to the previous project; refetch under the new one.
      void queryClient.resetQueries({
        predicate: (q) => q.queryKey[0] !== projectQueryKeys.list[0],
      });
    },
    [queryClient]
  );

  // Set by open/exit until the URL has caught up, so the effect below does
  // not mistake the in-between render for a param an in-app link dropped.
  const pending = useRef<string | null | undefined>(undefined);

  // URL -> selection.
  const urlSlug = projectFromSearch(location.search);
  useEffect(() => {
    if (pending.current !== undefined) {
      if (urlSlug === pending.current) pending.current = undefined;
      return;
    }
    if (urlSlug) {
      if (current && urlSlug === current.slug) {
        // Naming the current project is the same as not naming one.
        switchTo(null);
        navigate({ pathname: location.pathname, search: withProject(location.search, null), hash: location.hash }, { replace: true });
      } else {
        switchTo(urlSlug);
      }
    } else if (viewedSlug) {
      // An in-app link dropped the param: keep the past project open.
      navigate(
        { pathname: location.pathname, search: withProject(location.search, viewedSlug), hash: location.hash },
        { replace: true }
      );
    }
  }, [urlSlug, viewedSlug, current, location.pathname, location.search, location.hash, navigate, switchTo]);

  const openProject = useCallback(
    (slug: string, path = '/alerts') => {
      if (current && slug === current.slug) {
        pending.current = null;
        switchTo(null);
        navigate(path);
        return;
      }
      pending.current = slug;
      switchTo(slug);
      navigate(`${path}${withProject('', slug)}`);
    },
    [current, navigate, switchTo]
  );

  const exitProject = useCallback(() => {
    pending.current = null;
    switchTo(null);
    navigate(
      { pathname: location.pathname, search: withProject(location.search, null), hash: location.hash },
      { replace: true }
    );
  }, [location.hash, location.pathname, location.search, navigate, switchTo]);

  const viewed = viewedSlug ? projects.find((p) => p.slug === viewedSlug || p.id === viewedSlug) ?? null : null;
  const unknownSlug = viewedSlug && list.isSuccess && !viewed ? viewedSlug : null;

  const value = useMemo<ProjectView>(
    () => ({ viewed, viewedSlug, current, projects, unknownSlug, openProject, exitProject }),
    [viewed, viewedSlug, current, projects, unknownSlug, openProject, exitProject]
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
