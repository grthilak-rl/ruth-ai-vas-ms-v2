/**
 * The project view context and its hook (the provider is in
 * ProjectViewContext.tsx). See viewProject.ts for how requests are tagged.
 */

import { createContext, useContext } from 'react';
import type { ProjectBrief } from './projectsApi';

export interface ProjectView {
  /** The past project being viewed, or null in the current project. */
  viewed: ProjectBrief | null;
  /** The slug being viewed even before the project list has loaded. */
  viewedSlug: string | null;
  /** The current project; null between End and the next Start. */
  current: ProjectBrief | null;
  projects: ProjectBrief[];
  /** Set when the URL names a project that does not exist. */
  unknownSlug: string | null;
  openProject: (slug: string, path?: string) => void;
  exitProject: () => void;
}

export const ProjectViewContext = createContext<ProjectView | null>(null);

export function useProjectView(): ProjectView {
  const value = useContext(ProjectViewContext);
  if (!value) {
    // Outside the provider (tests, the kiosk viewing pane): current project.
    return {
      viewed: null,
      viewedSlug: null,
      current: null,
      projects: [],
      unknownSlug: null,
      openProject: () => undefined,
      exitProject: () => undefined,
    };
  }
  return value;
}
