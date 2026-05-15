/**
 * Bookmark Analyses List Page (Phase D.3).
 *
 * Shows the most recent analyses across all bookmarks, with a CTA to
 * submit a new one. Polls at ANALYSIS_LIST cadence; a new submission
 * invalidates the query so the row appears immediately.
 */

import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useBookmarkAnalysesListQuery, useBookmarksListQuery } from '../state';
import type {
  BookmarkAnalysis,
  BookmarkAnalysisListItem,
} from '../state/hooks/useBookmarkAnalysesQuery';
import type { VasBookmark } from '../state/hooks/useBookmarksQuery';
import { NewAnalysisForm } from '../components/bookmark-analyses/NewAnalysisForm';
import './BookmarkAnalysesListPage.css';

function formatRelative(iso: string): string {
  const d = new Date(iso);
  const seconds = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function formatDurationSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function StateBadge({ state }: { state: BookmarkAnalysisListItem['state'] }) {
  return <span className={`bml-state bml-state--${state}`}>{state}</span>;
}

export function BookmarkAnalysesListPage() {
  const navigate = useNavigate();
  const [formOpen, setFormOpen] = useState(false);
  const { data, isLoading, isError, refetch } = useBookmarkAnalysesListQuery(50);
  // Pre-fetch bookmarks here so the modal opens without a loading flash
  // (and so we can show the camera/time hint in the table without
  // adding a per-row query).
  const { data: bookmarksData } = useBookmarksListQuery(100);
  const bookmarksById = (bookmarksData ?? []).reduce<Record<string, VasBookmark>>(
    (acc: Record<string, VasBookmark>, b: VasBookmark) => {
      acc[b.id] = b;
      return acc;
    },
    {},
  );

  const handleCreated = useCallback(
    (analysis: BookmarkAnalysis) => {
      setFormOpen(false);
      navigate(`/bookmark-analyses/${analysis.id}`);
    },
    [navigate],
  );

  return (
    <div className="bml-page">
      <div className="bml-page__header">
        <h1>Bookmark Analyses</h1>
        <button
          type="button"
          className="bml-page__cta"
          onClick={() => setFormOpen(true)}
        >
          + New Analysis
        </button>
      </div>

      {isLoading && <div className="bml-empty">Loading…</div>}

      {isError && (
        <div className="bml-empty">
          <div className="bml-empty__title">Failed to load analyses</div>
          <button type="button" onClick={() => refetch()}>
            Retry
          </button>
        </div>
      )}

      {!isLoading && !isError && (data?.items.length ?? 0) === 0 && (
        <div className="bml-empty">
          <div className="bml-empty__title">No analyses yet</div>
          <div>
            Submit one with <strong>+ New Analysis</strong> above. Operators
            can re-run with different parameters at any time.
          </div>
        </div>
      )}

      {!isLoading && (data?.items.length ?? 0) > 0 && (
        <table className="bml-table">
          <thead>
            <tr>
              <th>Bookmark</th>
              <th>Model</th>
              <th>State</th>
              <th>Submitted</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((row: BookmarkAnalysisListItem) => {
              const bookmark = bookmarksById[row.vas_bookmark_id];
              const cameraName = bookmark?.device_name ?? '(camera unknown)';
              const bookmarkStart = bookmark
                ? new Date(bookmark.start_time).toLocaleString()
                : row.vas_bookmark_id.slice(0, 8);
              const duration =
                row.state === 'completed' && row.completed_at
                  ? formatDurationSeconds(
                      (new Date(row.completed_at).getTime() -
                        new Date(row.created_at).getTime()) /
                        1000,
                    )
                  : '—';
              return (
                <tr
                  key={row.id}
                  onClick={() => navigate(`/bookmark-analyses/${row.id}`)}
                >
                  <td>
                    <div>{cameraName}</div>
                    <div style={{ fontSize: '0.8rem', color: '#666' }}>
                      {bookmarkStart}
                    </div>
                  </td>
                  <td>{row.model_id}</td>
                  <td>
                    <StateBadge state={row.state} />
                  </td>
                  <td>{formatRelative(row.created_at)}</td>
                  <td>{duration}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {formOpen && (
        <NewAnalysisForm
          isOpen={formOpen}
          onClose={() => setFormOpen(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
}
