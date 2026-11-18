/**
 * Read-only project list (GET /api/v1/projects), open to every portal user.
 * Lifecycle actions and counts stay on the admin API (pages/admin/adminApi.ts).
 */

import { apiGet } from '../api/client';

export interface ProjectBrief {
  id: string;
  name: string;
  slug: string;
  state: 'active' | 'stopping' | 'stopped' | 'resuming' | 'ended' | 'archived';
  started_at: string;
  ended_at: string | null;
  /** The project new data is tagged with (or the last one, between End and Start). */
  is_current: boolean;
}

export interface ProjectBriefList {
  items: ProjectBrief[];
  current: ProjectBrief | null;
}

export interface ProjectCamera {
  id: string;
  name: string;
  display_name: string | null;
  enabled: boolean;
}

export async function fetchProjects(): Promise<ProjectBriefList> {
  return apiGet<ProjectBriefList>('/api/v1/projects');
}

export async function fetchProjectCameras(slug: string): Promise<ProjectCamera[]> {
  return apiGet<ProjectCamera[]>(`/api/v1/projects/${encodeURIComponent(slug)}/cameras`);
}

export const projectQueryKeys = {
  list: ['projects', 'list'] as const,
  cameras: (slug: string) => ['projects', 'cameras', slug] as const,
};
