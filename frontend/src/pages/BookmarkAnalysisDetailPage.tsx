/**
 * Bookmark Analysis Detail Page (Phase D.3).
 *
 * Shows one analysis with conditional polling — completed and failed
 * rows stop polling automatically (see useBookmarkAnalysisQuery).
 *
 * Body renders by state:
 *   - pending / running:  spinner + message
 *   - completed:          dispatches by model_id — TankOverflowSummary
 *                         for tank_overflow_monitoring, RawJsonSummary
 *                         fallback otherwise
 *   - failed:             error_message in an error box
 *
 * "Re-run" pre-fills the NewAnalysisForm with this analysis's params.
 */

import { useCallback, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { useBookmarkAnalysisQuery } from '../state';
import type {
  BookmarkAnalysis,
  TankOverflowSummary as TankSummary,
} from '../state/api/bookmarkAnalyses.api';
import { NewAnalysisForm } from '../components/bookmark-analyses/NewAnalysisForm';
import { RawJsonSummary } from '../components/bookmark-analyses/RawJsonSummary';
import { TankOverflowSummary } from '../components/bookmark-analyses/TankOverflowSummary';
import './BookmarkAnalysesListPage.css'; // shares the bml-state--* classes
import './BookmarkAnalysisDetailPage.css';

function StateBadge({ state }: { state: BookmarkAnalysis['state'] }) {
  return <span className={`bml-state bml-state--${state}`}>{state}</span>;
}

export function BookmarkAnalysisDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data, isLoading, isError } = useBookmarkAnalysisQuery(id);
  const [rerunOpen, setRerunOpen] = useState(false);

  const handleRerunCreated = useCallback(
    (created: BookmarkAnalysis) => {
      setRerunOpen(false);
      navigate(`/bookmark-analyses/${created.id}`);
    },
    [navigate],
  );

  if (isLoading) {
    return (
      <div className="bma-page">
        <div className="bma-running">
          <div className="bma-running__spinner" aria-hidden />
          <div>Loading analysis…</div>
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="bma-page">
        <div className="bma-error">
          Failed to load analysis {id}.
        </div>
      </div>
    );
  }

  const shortId = data.id.slice(0, 8);

  return (
    <div className="bma-page">
      <div className="bma-page__header">
        <div className="bma-page__header-left">
          <button
            type="button"
            className="bma-page__back"
            onClick={() => navigate('/bookmark-analyses')}
          >
            ← Back
          </button>
          <h1 className="bma-page__title">Analysis {shortId}</h1>
          <StateBadge state={data.state} />
        </div>
        <button
          type="button"
          className="bma-cta-rerun"
          onClick={() => setRerunOpen(true)}
        >
          Re-run
        </button>
      </div>

      <dl className="bma-meta">
        <dt className="bma-meta__label">Bookmark</dt>
        <dd className="bma-meta__value">{data.vas_bookmark_id}</dd>

        <dt className="bma-meta__label">Model</dt>
        <dd className="bma-meta__value">
          {data.model_id}
          {data.model_version ? `:${data.model_version}` : ''}
        </dd>

        <dt className="bma-meta__label">Parameters</dt>
        <dd className="bma-meta__value">
          <pre className="bma-json" style={{ maxHeight: 200 }}>
            {JSON.stringify(data.parameters ?? {}, null, 2)}
          </pre>
        </dd>

        <dt className="bma-meta__label">Submitted</dt>
        <dd>{new Date(data.created_at).toLocaleString()}</dd>

        {data.started_at && (
          <>
            <dt className="bma-meta__label">Started</dt>
            <dd>{new Date(data.started_at).toLocaleString()}</dd>
          </>
        )}

        {data.completed_at && (
          <>
            <dt className="bma-meta__label">Completed</dt>
            <dd>{new Date(data.completed_at).toLocaleString()}</dd>
          </>
        )}
      </dl>

      <div className="bma-body">
        {data.state === 'pending' && (
          <div className="bma-running">
            <div className="bma-running__spinner" aria-hidden />
            <div>Waiting to start…</div>
          </div>
        )}

        {data.state === 'running' && (
          <div className="bma-running">
            <div className="bma-running__spinner" aria-hidden />
            <div>Analyzing — this can take a few minutes for long bookmarks.</div>
          </div>
        )}

        {data.state === 'failed' && (
          <div className="bma-error">
            {data.error_message ?? 'Analysis failed (no error message recorded).'}
          </div>
        )}

        {data.state === 'completed' && (
          data.model_id === 'tank_overflow_monitoring' && data.summary ? (
            <TankOverflowSummary summary={data.summary as TankSummary} />
          ) : (
            <RawJsonSummary summary={data.summary as Record<string, unknown> | null} />
          )
        )}
      </div>

      {rerunOpen && (
        <NewAnalysisForm
          isOpen={rerunOpen}
          onClose={() => setRerunOpen(false)}
          onCreated={handleRerunCreated}
          initialBookmarkId={data.vas_bookmark_id}
          initialModelId={data.model_id}
          initialParameters={data.parameters ?? undefined}
        />
      )}
    </div>
  );
}
