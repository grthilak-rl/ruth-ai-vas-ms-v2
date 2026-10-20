/**
 * "Download snapshots" — bulk evidence export for the AI engineer.
 *
 * Four states in one dialog: choose options, confirm what the preview says
 * it will contain, watch it build, download. Admin-gated, so an operator
 * without a token is shown the inline sign-in rather than a dead button.
 *
 * The preview matters more than it looks. The inferred-frame feature
 * started partway through this site's history, so a wide date range can be
 * mostly violations that only ever had a scene snapshot — and a snapshot is
 * a later capture whose boxes do not line up with the detection. The
 * "N of M have no inferred frame" line is there so nobody discovers that
 * after unzipping 400MB.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import './DismissConfirmationDialog.css';
import './ExportDialog.css';

import { InlineAdminSignIn } from '../../pages/settings/InlineAdminSignIn';
import { useAdminSession } from '../../pages/admin';
import {
  createExport,
  downloadExport,
  formatBytes,
  getExport,
  previewExport,
  type ExportFilters,
  type ExportJob,
  type ExportPreview,
  type ExportScope,
} from '../../state/api/violationExports';

/** How often to ask the server how the build is going. */
const POLL_MS = 1500;
/** Stop polling eventually, so a stuck job does not poll for ever. */
const POLL_CEILING_MS = 10 * 60 * 1000;

export interface ExportDialogProps {
  filters: ExportFilters;
  /** Selected incidents, or null to export everything matching the filters. */
  incidentIds: string[] | null;
  onClose: () => void;
}

export function ExportDialog({ filters, incidentIds, onClose }: ExportDialogProps) {
  const { isSignedIn } = useAdminSession();
  const [scope, setScope] = useState<ExportScope>('one_per_incident');
  const [annotated, setAnnotated] = useState(true);
  const [includeSnapshots, setIncludeSnapshots] = useState(false);

  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);

  const [job, setJob] = useState<ExportJob | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);

  const body = useCallback(
    () => ({
      filters,
      scope,
      annotated,
      include_snapshots: includeSnapshots,
      incident_ids: incidentIds,
    }),
    [filters, scope, annotated, includeSnapshots, incidentIds]
  );

  // Re-preview whenever an option changes: the counts and the size estimate
  // both depend on them, and a stale estimate is worse than none.
  useEffect(() => {
    if (!isSignedIn || job) return;
    let cancelled = false;
    setIsPreviewing(true);
    setPreviewError(null);
    previewExport(body())
      .then((result) => {
        if (!cancelled) setPreview(result);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setPreview(null);
          setPreviewError(error instanceof Error ? error.message : 'Preview failed');
        }
      })
      .finally(() => {
        if (!cancelled) setIsPreviewing(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isSignedIn, job, body]);

  // Poll while the archive is being built.
  const startedAt = useRef<number>(0);
  useEffect(() => {
    if (!job || job.status !== 'building') return;
    if (!startedAt.current) startedAt.current = Date.now();
    const timer = setInterval(() => {
      if (Date.now() - startedAt.current > POLL_CEILING_MS) {
        clearInterval(timer);
        setJobError('The export is taking longer than expected; check back later.');
        return;
      }
      getExport(job.id)
        .then(setJob)
        .catch((error: unknown) => {
          setJobError(error instanceof Error ? error.message : 'Lost track of the export');
        });
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [job]);

  const start = async () => {
    setIsStarting(true);
    setJobError(null);
    try {
      startedAt.current = 0;
      setJob(await createExport(body()));
    } catch (error: unknown) {
      setJobError(error instanceof Error ? error.message : 'Could not start the export');
    } finally {
      setIsStarting(false);
    }
  };

  const download = async () => {
    if (!job) return;
    setIsDownloading(true);
    setJobError(null);
    try {
      await downloadExport(job.id, `violations_${job.id}.zip`);
    } catch (error: unknown) {
      setJobError(error instanceof Error ? error.message : 'Download failed');
    } finally {
      setIsDownloading(false);
    }
  };

  if (!isSignedIn) {
    return (
      <div className="dismiss-dialog-backdrop">
        <div className="export-dialog" role="dialog" aria-label="Download snapshots">
        <h2>Download snapshots</h2>
        <p>
          Bulk evidence export includes identifiable imagery, so it needs an
          admin sign-in.
        </p>
          <InlineAdminSignIn capability="export violation evidence" />
          <div className="export-dialog__actions">
            <button type="button" onClick={onClose}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    );
  }

  const scopeLabel =
    incidentIds && incidentIds.length > 0
      ? `${incidentIds.length} selected incident${incidentIds.length === 1 ? '' : 's'}`
      : 'the current filters';

  return (
    <div className="dismiss-dialog-backdrop">
      <div className="export-dialog" role="dialog" aria-label="Download snapshots">
      <h2>Download snapshots</h2>
      <p className="export-dialog__scope">Exporting {scopeLabel}.</p>

      {!job && (
        <>
          <fieldset>
            <legend>How many</legend>
            <label>
              <input
                type="radio"
                name="scope"
                checked={scope === 'one_per_incident'}
                onChange={() => setScope('one_per_incident')}
              />
              One image per incident (highest confidence)
            </label>
            <label>
              <input
                type="radio"
                name="scope"
                checked={scope === 'all'}
                onChange={() => setScope('all')}
              />
              Every violation
            </label>
          </fieldset>

          <fieldset>
            <legend>Contents</legend>
            <label>
              <input
                type="checkbox"
                checked={annotated}
                onChange={(e) => setAnnotated(e.target.checked)}
              />
              Also include copies with boxes drawn (<code>annotated/</code>)
            </label>
            <label>
              <input
                type="checkbox"
                checked={includeSnapshots}
                onChange={(e) => setIncludeSnapshots(e.target.checked)}
              />
              Fall back to the scene snapshot where no inferred frame exists
            </label>
            {includeSnapshots && (
              <p className="export-dialog__warning">
                Scene snapshots are a later capture, so their boxes do not line
                up with the detection and they are never annotated. They are
                also about three times larger and each one is fetched from VAS.
              </p>
            )}
          </fieldset>

          <div className="export-dialog__preview" aria-live="polite">
            {isPreviewing && <span>Checking…</span>}
            {previewError && <span className="export-dialog__error">{previewError}</span>}
            {preview && !isPreviewing && (
              <>
                <p>
                  <strong>{preview.violations_in_export.toLocaleString()}</strong>{' '}
                  image{preview.violations_in_export === 1 ? '' : 's'}, about{' '}
                  <strong>{formatBytes(preview.estimated_bytes)}</strong>.
                </p>
                {preview.without_inferred_frame > 0 && (
                  <p className="export-dialog__warning">
                    {preview.without_inferred_frame.toLocaleString()} of{' '}
                    {preview.violations_in_export.toLocaleString()} have no
                    inferred frame
                    {includeSnapshots
                      ? ' and will use the scene snapshot.'
                      : ' and will be skipped. Enable the snapshot fallback to include them.'}
                  </p>
                )}
                {!preview.within_cap && (
                  <p className="export-dialog__error">
                    Too large: the limit is{' '}
                    {preview.max_violations.toLocaleString()} violations. Narrow
                    the date range, camera or type.
                  </p>
                )}
              </>
            )}
          </div>

          {jobError && <p className="export-dialog__error">{jobError}</p>}

          <div className="export-dialog__actions">
            <button type="button" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              onClick={start}
              disabled={
                isStarting ||
                isPreviewing ||
                !preview ||
                !preview.within_cap ||
                preview.violations_in_export === 0
              }
            >
              {isStarting ? 'Starting…' : 'Build archive'}
            </button>
          </div>
        </>
      )}

      {job && (
        <div className="export-dialog__job" aria-live="polite">
          {job.status === 'building' && (
            <>
              <p>
                Building… {job.done.toLocaleString()} of{' '}
                {job.total.toLocaleString()}
              </p>
              <progress value={job.done} max={Math.max(job.total, 1)} />
            </>
          )}
          {job.status === 'ready' && (
            <>
              <p>
                Ready: {job.images.toLocaleString()} image
                {job.images === 1 ? '' : 's'}, {formatBytes(job.size_bytes)}.
                {job.without_inferred_frame > 0 &&
                  ` ${job.without_inferred_frame.toLocaleString()} had no inferred frame.`}
                {job.skipped > 0 && ` ${job.skipped.toLocaleString()} could not be read.`}
              </p>
              <p className="export-dialog__hint">
                The archive is deleted automatically after 24 hours.
              </p>
            </>
          )}
          {job.status === 'failed' && (
            <p className="export-dialog__error">
              Export failed{job.error ? `: ${job.error}` : '.'}
            </p>
          )}
          {job.status === 'expired' && (
            <p className="export-dialog__error">
              This archive has expired. Start a new export.
            </p>
          )}

          {jobError && <p className="export-dialog__error">{jobError}</p>}

          <div className="export-dialog__actions">
            <button type="button" onClick={onClose}>
              Close
            </button>
            {job.status === 'ready' && (
              <button type="button" onClick={download} disabled={isDownloading}>
                {isDownloading ? 'Downloading…' : 'Download ZIP'}
              </button>
            )}
          </div>
          </div>
        )}
      </div>
    </div>
  );
}
