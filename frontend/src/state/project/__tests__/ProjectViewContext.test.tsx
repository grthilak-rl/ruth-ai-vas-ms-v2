// @vitest-environment jsdom
/**
 * Project view mode in the portal: the URL selects a past project, the
 * selection survives in-app navigation and refreshes, the banner says
 * which project is shown (and that live pages are live), and "Back to
 * current project" leaves it.
 */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectBanner } from '../../../components/project/ProjectBanner';
import { ProjectViewProvider } from '../ProjectViewContext';
import { useProjectView } from '../projectView';
import { _resetForTests, getViewedProject } from '../viewProject';

const api = vi.hoisted(() => ({
  fetchProjects: vi.fn(async () => ({
    items: [
      { id: 'p-dev', name: 'Post HPCL Dev', slug: 'post-hpcl-dev', state: 'active', started_at: '2026-11-17T09:00:00Z', ended_at: null, is_current: true },
      { id: 'p-hpcl', name: 'HPCL', slug: 'hpcl', state: 'ended', started_at: '2026-10-16T13:20:00Z', ended_at: '2026-11-17T08:00:00Z', is_current: false },
    ],
    current: { id: 'p-dev', name: 'Post HPCL Dev', slug: 'post-hpcl-dev', state: 'active', started_at: '2026-11-17T09:00:00Z', ended_at: null, is_current: true },
  })),
}));
vi.mock('../projectsApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../projectsApi')>()),
  ...api,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement;

function Opener() {
  const { openProject } = useProjectView();
  return (
    <button type="button" data-testid="open-hpcl" onClick={() => openProject('hpcl')}>
      open
    </button>
  );
}

function Shell() {
  return (
    <ProjectViewProvider>
      <ProjectBanner />
      <Opener />
      <Outlet />
    </ProjectViewProvider>
  );
}

async function render(url: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const resetSpy = vi.spyOn(queryClient, 'resetQueries');
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: <Shell />,
        children: [
          { path: 'alerts', element: <p>alerts</p> },
          { path: 'analytics', element: <p>analytics</p> },
          { path: 'cameras', element: <p>cameras</p> },
        ],
      },
    ],
    { initialEntries: [url] }
  );
  await act(async () => {
    root = createRoot(container);
    root.render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    );
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
  return { router, resetSpy };
}

const banner = () => container.querySelector('.project-banner')?.textContent ?? null;
const click = async (el: Element | null) => {
  await act(async () => {
    (el as HTMLElement).click();
  });
};

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container.remove();
  _resetForTests();
});

describe('project view mode', () => {
  it('opens the project named in the URL and shows the banner', async () => {
    await render('/alerts?project=hpcl');
    expect(getViewedProject()).toBe('hpcl');
    expect(banner()).toContain('Viewing HPCL');
    expect(banner()).toContain('ended 17 Nov');
    expect(banner()).toContain('Back to current project');
  });

  it('keeps the project across in-app navigation', async () => {
    const { router } = await render('/alerts?project=hpcl');
    await act(async () => {
      await router.navigate('/analytics');
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(router.state.location.pathname).toBe('/analytics');
    expect(router.state.location.search).toBe('?project=hpcl');
    expect(getViewedProject()).toBe('hpcl');
  });

  it('Back to current project leaves the past project', async () => {
    const { router } = await render('/alerts?status=open&project=hpcl');
    await click(container.querySelector('.project-banner__back'));
    expect(getViewedProject()).toBeNull();
    expect(router.state.location.search).toBe('?status=open');
    expect(banner()).toBeNull();
  });

  it('naming the current project is the same as naming none', async () => {
    const { router } = await render('/alerts?project=post-hpcl-dev');
    expect(getViewedProject()).toBeNull();
    expect(router.state.location.search).toBe('');
    expect(banner()).toBeNull();
  });

  it('says live pages show the current project', async () => {
    await render('/cameras?project=hpcl');
    expect(banner()).toContain('This page is live and shows the current project (Post HPCL Dev)');
  });

  it('flags a project that does not exist', async () => {
    await render('/alerts?project=nope');
    expect(container.querySelector('.project-banner--error')?.textContent).toContain('There is no project nope');
  });

  it('between End and Start nothing is current, and the ended project opens with the banner', async () => {
    api.fetchProjects.mockResolvedValueOnce({
      items: [
        { id: 'p-hpcl', name: 'HPCL', slug: 'hpcl', state: 'ended', started_at: '2026-10-16T13:20:00Z', ended_at: '2026-11-17T08:00:00Z', is_current: false },
      ],
      current: null,
    } as never);
    const { router } = await render('/alerts?project=hpcl');
    expect(router.state.location.search).toBe('?project=hpcl');
    expect(getViewedProject()).toBe('hpcl');
    expect(banner()).toContain('Viewing HPCL');
  });

  it('Open switches project, navigates with the param and resets the cache', async () => {
    const { router, resetSpy } = await render('/analytics');
    expect(banner()).toBeNull();
    await click(container.querySelector('[data-testid="open-hpcl"]'));
    expect(router.state.location.pathname).toBe('/alerts');
    expect(router.state.location.search).toBe('?project=hpcl');
    expect(getViewedProject()).toBe('hpcl');
    expect(resetSpy).toHaveBeenCalled();
    expect(banner()).toContain('Viewing HPCL');
  });
});
