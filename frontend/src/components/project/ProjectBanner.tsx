import { useLocation } from 'react-router-dom';
import { useProjectView } from '../../state/project/projectView';
import { formatDay, isLivePage } from './projectPages';
import './ProjectBanner.css';

/**
 * Persistent banner while a past project is open:
 *
 *   Viewing HPCL · ended 17 Nov · Back to current project
 *
 * On live pages (Cameras, live view, Bookmark monitoring, System Health and
 * the other configuration tabs) it adds that they show the current project:
 * those pages describe what is running now, whatever project is viewed.
 */

function stateText(state: string, endedAt: string | null): string {
  if (state === 'ended' || state === 'archived') return endedAt ? `ended ${formatDay(endedAt)}` : 'ended';
  return state;
}

export function ProjectBanner() {
  const { viewed, viewedSlug, current, unknownSlug, exitProject } = useProjectView();
  const { pathname } = useLocation();
  if (!viewedSlug) return null;

  if (unknownSlug) {
    return (
      <div className="project-banner project-banner--error" role="alert">
        <span>
          There is no project <strong>{unknownSlug}</strong>.
        </span>
        <button type="button" className="project-banner__back" onClick={exitProject}>
          Back to current project
        </button>
      </div>
    );
  }

  const live = isLivePage(pathname);
  return (
    <div className="project-banner" role="status" aria-live="polite">
      <span className="project-banner__what">
        Viewing <strong>{viewed?.name ?? viewedSlug}</strong>
        {viewed && <span className="project-banner__sep"> · {stateText(viewed.state, viewed.ended_at)}</span>}
      </span>
      {live && (
        <span className="project-banner__live">
          This page is live and shows the current project
          {current ? ` (${current.name})` : ''}.
        </span>
      )}
      <button type="button" className="project-banner__back" onClick={exitProject}>
        Back to current project
      </button>
    </div>
  );
}
