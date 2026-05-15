/**
 * New / Re-run bookmark-analysis form (Phase D.3).
 *
 * Modal form. Reuses VideoCanvas — the same component live monitoring
 * uses for tank-corner selection — pointed at the bookmark's preview
 * frame instead of a live stream. The four-click UX is identical.
 *
 * Optional initial* props pre-fill the form when re-running an
 * existing analysis from the detail page.
 */

import { useEffect, useMemo, useState } from 'react';

import { VideoCanvas } from '../VideoCanvas';
import type { Point } from '../../types/geofencing';
import {
  useBookmarksListQuery,
  useModelsStatusQuery,
  useSubmitBookmarkAnalysisMutation,
  type VasBookmark,
} from '../../state';
import { getBookmarkPreviewFrameUrl } from '../../state/api/bookmarkAnalyses.api';
import type {
  BookmarkAnalysis,
  BookmarkAnalysisSubmitRequest,
} from '../../state/hooks/useBookmarkAnalysesQuery';
import './NewAnalysisForm.css';

interface NewAnalysisFormProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (created: BookmarkAnalysis) => void;
  /** Re-run: pre-select this bookmark. */
  initialBookmarkId?: string;
  /** Re-run: pre-select this model. */
  initialModelId?: string;
  /** Re-run: pre-fill parameters (tank_corners, capacity_liters, …). */
  initialParameters?: Record<string, unknown>;
}

const SAMPLING_FPS_DEFAULT = 1.0;
const SAMPLING_FPS_MIN = 0.1;
const SAMPLING_FPS_MAX = 10.0;

type CornersArray = number[][]; // [[x, y], ...]

function cornersFromParams(params: Record<string, unknown> | undefined): Point[] {
  const raw = params?.tank_corners as unknown;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((pt) =>
      Array.isArray(pt) && pt.length === 2
        ? { x: Number(pt[0]), y: Number(pt[1]) }
        : null,
    )
    .filter((p): p is Point => p !== null);
}

export function NewAnalysisForm({
  isOpen,
  onClose,
  onCreated,
  initialBookmarkId,
  initialModelId,
  initialParameters,
}: NewAnalysisFormProps) {
  const { data: bookmarks, isLoading: bookmarksLoading } =
    useBookmarksListQuery(100);
  const { data: modelsData } = useModelsStatusQuery();
  const submitMutation = useSubmitBookmarkAnalysisMutation();

  const [bookmarkId, setBookmarkId] = useState<string>(initialBookmarkId ?? '');
  const [modelId, setModelId] = useState<string>(
    initialModelId ?? 'tank_overflow_monitoring',
  );

  // Tank-specific state
  const [corners, setCorners] = useState<Point[]>(
    cornersFromParams(initialParameters),
  );
  const [capacityLiters, setCapacityLiters] = useState<number>(
    (initialParameters?.capacity_liters as number | undefined) ?? 1000,
  );
  const [alertThreshold, setAlertThreshold] = useState<number>(
    (initialParameters?.alert_threshold as number | undefined) ?? 90,
  );

  // Universal
  const [samplingFps, setSamplingFps] = useState<number>(
    (initialParameters?.sampling_fps as number | undefined) ??
      SAMPLING_FPS_DEFAULT,
  );

  const [formError, setFormError] = useState<string | null>(null);

  // Default-select the first bookmark when none is pre-set and the
  // list arrives.
  useEffect(() => {
    if (!bookmarkId && bookmarks && bookmarks.length > 0) {
      setBookmarkId(bookmarks[0].id);
    }
  }, [bookmarks, bookmarkId]);

  const healthyModels = useMemo(
    () =>
      (modelsData?.models ?? []).filter(
        (m) => m.health === 'healthy' || m.health === 'degraded',
      ),
    [modelsData],
  );

  const isTankModel = modelId === 'tank_overflow_monitoring';
  const isSupportedModel = isTankModel;

  // Polygon click handler — same four-click logic as GeofenceSetupModal.
  const handleCanvasClick = (point: Point) => {
    if (!isTankModel) return;
    if (corners.length >= 4) return;
    setCorners([...corners, point]);
  };

  const handleResetCorners = () => setCorners([]);

  const canSubmit =
    !!bookmarkId &&
    isSupportedModel &&
    corners.length === 4 &&
    samplingFps >= SAMPLING_FPS_MIN &&
    samplingFps <= SAMPLING_FPS_MAX &&
    !submitMutation.isPending;

  const handleSubmit = async () => {
    setFormError(null);
    if (!canSubmit) return;
    const parameters: Record<string, unknown> = {
      sampling_fps: samplingFps,
    };
    if (isTankModel) {
      parameters.tank_corners = corners.map((p) => [p.x, p.y]) as CornersArray;
      parameters.capacity_liters = capacityLiters;
      parameters.alert_threshold = alertThreshold;
    }

    const request: BookmarkAnalysisSubmitRequest = {
      vas_bookmark_id: bookmarkId,
      model_id: modelId,
      parameters,
    };

    try {
      const created = await submitMutation.mutateAsync(request);
      onCreated(created);
    } catch (err) {
      // Try to surface a clean message from the backend's structured error.
      // apiPost throws an ApiError with .message / .detail; fall back to
      // string() if those aren't present.
      const message =
        (err as { message?: string }).message ??
        (err as { detail?: unknown }).detail?.toString?.() ??
        String(err);
      setFormError(message);
    }
  };

  if (!isOpen) return null;

  const previewUrl = bookmarkId ? getBookmarkPreviewFrameUrl(bookmarkId) : '';

  const cornerHint =
    corners.length === 0
      ? 'Click the top-left corner of the tank opening.'
      : corners.length === 1
        ? 'Click the top-right corner.'
        : corners.length === 2
          ? 'Click the bottom-right corner.'
          : corners.length === 3
            ? 'Click the bottom-left corner.'
            : 'All 4 corners defined — ready to submit.';

  return (
    <div className="naf-overlay" role="dialog" aria-modal="true">
      <div className="naf-modal">
        <div className="naf-modal__header">
          <h2 className="naf-modal__title">
            {initialBookmarkId ? 'Re-run Analysis' : 'New Bookmark Analysis'}
          </h2>
          <button
            type="button"
            className="naf-modal__close"
            onClick={onClose}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="naf-modal__body">
          {/* Step 1 — Bookmark picker */}
          <div className="naf-field">
            <label className="naf-field__label" htmlFor="naf-bookmark">
              Bookmark
            </label>
            <select
              id="naf-bookmark"
              className="naf-field__select"
              value={bookmarkId}
              onChange={(e) => {
                setBookmarkId(e.target.value);
                // Tank corners are coordinate-dependent on the
                // selected bookmark's frame — reset on change.
                setCorners([]);
              }}
              disabled={bookmarksLoading}
            >
              <option value="" disabled>
                {bookmarksLoading ? 'Loading bookmarks…' : 'Select a bookmark'}
              </option>
              {(bookmarks ?? []).map((b: VasBookmark) => {
                const cam = b.device_name ?? '(camera unknown)';
                const when = new Date(b.start_time).toLocaleString();
                return (
                  <option key={b.id} value={b.id}>
                    {cam} — {when} ({b.duration_seconds.toFixed(0)}s)
                  </option>
                );
              })}
            </select>
          </div>

          {/* Step 2 — Model picker */}
          <div className="naf-field">
            <label className="naf-field__label" htmlFor="naf-model">
              Model
            </label>
            <select
              id="naf-model"
              className="naf-field__select"
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
            >
              {healthyModels.length === 0 && (
                <option value="">No healthy models</option>
              )}
              {healthyModels.map((m) => (
                <option key={m.model_id} value={m.model_id}>
                  {m.model_id}
                </option>
              ))}
            </select>
          </div>

          {!isSupportedModel && (
            <div className="naf-info">
              Configuration for <strong>{modelId}</strong> is coming in a later
              phase. Pick <strong>tank_overflow_monitoring</strong> to submit
              an analysis now.
            </div>
          )}

          {/* Step 3 — Tank corners on preview frame */}
          {isTankModel && bookmarkId && (
            <>
              <div className="naf-field">
                <label className="naf-field__label">
                  Tank corners — click 4 points
                </label>
                <div className="naf-canvas-wrap__hint">
                  {cornerHint}
                  {corners.length > 0 && (
                    <button
                      type="button"
                      className="naf-canvas-wrap__reset"
                      onClick={handleResetCorners}
                    >
                      Reset
                    </button>
                  )}
                </div>
                <div className="naf-canvas-wrap">
                  <VideoCanvas
                    videoUrl={previewUrl}
                    onClick={handleCanvasClick}
                    corners={corners}
                    isDrawing={false}
                    mode="manual"
                  />
                </div>
              </div>

              <div className="naf-field__row">
                <div className="naf-field">
                  <label
                    className="naf-field__label"
                    htmlFor="naf-capacity"
                  >
                    Tank capacity (liters)
                  </label>
                  <input
                    id="naf-capacity"
                    type="number"
                    min={1}
                    max={1000000}
                    className="naf-field__input"
                    value={capacityLiters}
                    onChange={(e) => setCapacityLiters(Number(e.target.value))}
                  />
                </div>
                <div className="naf-field">
                  <label
                    className="naf-field__label"
                    htmlFor="naf-threshold"
                  >
                    Alert threshold (%)
                  </label>
                  <input
                    id="naf-threshold"
                    type="number"
                    min={50}
                    max={100}
                    className="naf-field__input"
                    value={alertThreshold}
                    onChange={(e) => setAlertThreshold(Number(e.target.value))}
                  />
                </div>
              </div>
            </>
          )}

          {/* Step 4 — Universal: sampling fps */}
          <div className="naf-field">
            <label className="naf-field__label" htmlFor="naf-fps">
              Sampling rate (fps, {SAMPLING_FPS_MIN}–{SAMPLING_FPS_MAX})
            </label>
            <input
              id="naf-fps"
              type="number"
              step={0.1}
              min={SAMPLING_FPS_MIN}
              max={SAMPLING_FPS_MAX}
              className="naf-field__input"
              value={samplingFps}
              onChange={(e) => setSamplingFps(Number(e.target.value))}
            />
          </div>

          {formError && <div className="naf-error">{formError}</div>}
        </div>

        <div className="naf-modal__footer">
          <button
            type="button"
            className="naf-modal__button"
            onClick={onClose}
            disabled={submitMutation.isPending}
          >
            Cancel
          </button>
          <button
            type="button"
            className="naf-modal__button naf-modal__button--primary"
            onClick={handleSubmit}
            disabled={!canSubmit}
          >
            {submitMutation.isPending ? 'Submitting…' : 'Submit Analysis'}
          </button>
        </div>
      </div>
    </div>
  );
}
