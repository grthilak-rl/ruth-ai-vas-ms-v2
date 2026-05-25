/**
 * Bookmark Monitoring page (D.6).
 *
 * Three things, top to bottom:
 *   1. Bookmark dropdown — VAS bookmarks from useBookmarksListQuery
 *   2. AI model selector — reuses AIModelSelector + its model-aware
 *      GeofenceSetupModal so tank_overflow gets a tank_corners prompt
 *      and geo_fencing gets a zones prompt; fall_detection and
 *      ppe_detection run immediately with no config.
 *   3. BookmarkMonitoringView — the <video> + canvas overlay,
 *      pointing the live-monitoring detection managers at a
 *      recorded bookmark instead of a WebRTC stream.
 *
 * Ephemeral: nothing is persisted. Pick a bookmark, pick a model,
 * press play; switch model or bookmark at will; nothing leaves a
 * trace. Identical to live monitoring's mental model, just with a
 * recorded video as the source.
 */

import { useMemo, useState } from 'react';

import { AIModelSelector, type AIModel } from '../components/cameras/AIModelSelector';
import { BookmarkMonitoringView } from '../components/bookmark-monitoring/BookmarkMonitoringView';
import { useBookmarksListQuery } from '../state/hooks/useBookmarksQuery';
import { useModelsStatusQuery } from '../state/hooks/useModelsStatusQuery';
import type { ModelStatusInfo } from '../state/api/models.api';
import type { ModelConfig } from '../types/geofencing';
import { getBookmarkPreviewFrameUrl } from '../state/api/bookmarkAnalyses.api';

import './BookmarkMonitoringPage.css';

/** Models that need a configuration step before they can run. Mirrors
 *  CameraMonitoringDashboard's classification so the operator experience
 *  is identical to live monitoring. */
const MODELS_REQUIRING_CONFIG = new Set([
  'tank_overflow_monitoring',
  'geo_fencing',
]);

interface SelectedModelState {
  modelId: string | null;
  config: ModelConfig | null;
}

function formatBookmarkOption(b: {
  device_name: string | null;
  label: string | null;
  duration_seconds: number;
  created_at: string;
}): string {
  const cam = b.device_name ?? 'Unknown camera';
  const when = new Date(b.created_at).toLocaleString();
  const durMin = Math.floor(b.duration_seconds / 60);
  const durSec = Math.round(b.duration_seconds % 60);
  const dur =
    durMin > 0 ? `${durMin}m${durSec ? ` ${durSec}s` : ''}` : `${durSec}s`;
  const label = b.label ? ` — ${b.label}` : '';
  return `${cam} • ${when} • ${dur}${label}`;
}

/** Convert a runtime ModelStatusInfo into the AIModel shape the
 *  AIModelSelector wants. Mirrors CameraMonitoringDashboard's
 *  conversion verbatim — same state mapping, same inline display-name
 *  derivation, same `_container` → `(Legacy)` suffix. We deliberately
 *  do NOT use humanizeModelId here: that helper returns the generic
 *  string "Detection" for operators (a HARD RULE for the operator-
 *  facing model-name policy), which would make every row in the
 *  AIModelSelector say "Detection". Live monitoring sidesteps it the
 *  same way. */
function toAIModel(
  m: ModelStatusInfo,
  enabledModelId: string | null,
): AIModel {
  const isEnabled = m.model_id === enabledModelId;
  let state: AIModel['state'];
  if (m.health === 'unhealthy' || m.status === 'error') {
    state = 'unavailable';
  } else if (m.health === 'degraded') {
    state = isEnabled ? 'degraded' : 'inactive';
  } else if (isEnabled) {
    state = 'active';
  } else {
    state = 'inactive';
  }
  let displayName = m.model_id
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
  if (m.model_id.includes('_container')) {
    displayName = displayName.replace(' Container', ' (Legacy)');
  }
  return {
    id: m.model_id,
    name: displayName,
    state,
    requiresGeofencing: MODELS_REQUIRING_CONFIG.has(m.model_id),
  };
}

export function BookmarkMonitoringPage() {
  const [selectedBookmarkId, setSelectedBookmarkId] = useState<string | null>(
    null,
  );
  const [selected, setSelected] = useState<SelectedModelState>({
    modelId: null,
    config: null,
  });

  const bookmarksQ = useBookmarksListQuery(50);
  const modelsQ = useModelsStatusQuery();

  const aiModels: AIModel[] = useMemo(() => {
    const list = modelsQ.data?.models ?? [];
    return list
      .filter((m) => m.health === 'healthy' || m.health === 'degraded')
      .map((m) => toAIModel(m, selected.modelId));
  }, [modelsQ.data, selected.modelId]);

  const modelConfigs: Record<string, ModelConfig> = useMemo(() => {
    if (!selected.modelId || !selected.config) return {};
    return { [selected.modelId]: selected.config };
  }, [selected]);

  /**
   * AIModelSelector emits toggles. We coerce its multi-select shape
   * into single-select: enabling X disables anything else; disabling
   * the active model clears selection.
   */
  const handleModelToggle = (
    modelId: string,
    enabled: boolean,
    config?: ModelConfig,
  ) => {
    if (enabled) {
      setSelected({ modelId, config: config ?? null });
    } else if (selected.modelId === modelId) {
      setSelected({ modelId: null, config: null });
    }
  };

  // The preview-frame URL (D.3) is the still-image background for
  // GeofenceSetupModal. The modal's VideoCanvas already renders its
  // `videoUrl` prop as an <img>, so this drops in unchanged.
  const previewFrameUrl = selectedBookmarkId
    ? getBookmarkPreviewFrameUrl(selectedBookmarkId)
    : '';

  return (
    <div className="bmp">
      <header className="bmp__header">
        <h1 className="bmp__title">Bookmark Monitoring</h1>
        <p className="bmp__subtitle">
          Run AI models on a recorded bookmark, with the same overlays as
          live camera monitoring. Selections are ephemeral — nothing is
          persisted.
        </p>
      </header>

      <div className="bmp__controls">
        <label className="bmp__control">
          <span className="bmp__control-label">Bookmark</span>
          <select
            className="bmp__select"
            value={selectedBookmarkId ?? ''}
            onChange={(e) => setSelectedBookmarkId(e.target.value || null)}
            // Only disable on a genuine error. Disabling on isLoading
            // greys the control out for ~70ms and reads as frozen
            // even though the round-trip is already fast.
            disabled={bookmarksQ.isError}
          >
            <option value="">
              {bookmarksQ.isLoading
                ? 'Loading bookmarks…'
                : bookmarksQ.isError
                  ? 'Failed to load bookmarks'
                  : '— Select a bookmark —'}
            </option>
            {(bookmarksQ.data ?? []).map((b) => (
              <option key={b.id} value={b.id}>
                {formatBookmarkOption(b)}
              </option>
            ))}
          </select>
          {bookmarksQ.isError && (
            <span className="bmp__error">
              Could not load bookmarks. Reload to retry.
            </span>
          )}
        </label>

        <div className="bmp__control bmp__control--model">
          <span className="bmp__control-label">AI Model</span>
          <AIModelSelector
            // Pass a stable empty string when no bookmark is selected
            // so the component still mounts; the trigger is disabled
            // and unreachable in that state, so cameraId/videoUrl
            // are unused by the user.
            cameraId={
              selectedBookmarkId
                ? `bookmark:${selectedBookmarkId}`
                : 'bookmark:none'
            }
            cameraName="Bookmark"
            videoUrl={previewFrameUrl}
            models={selectedBookmarkId ? aiModels : []}
            onModelToggle={handleModelToggle}
            modelConfigs={modelConfigs}
            disabled={!selectedBookmarkId}
          />
          {modelsQ.isError && (
            <span className="bmp__error">
              Could not load AI models. Reload to retry.
            </span>
          )}
        </div>
      </div>

      <div className="bmp__view">
        {selectedBookmarkId ? (
          <BookmarkMonitoringView
            // Re-mount on bookmark change so the <video> resets cleanly,
            // along with any stale manager state.
            key={selectedBookmarkId}
            vasBookmarkId={selectedBookmarkId}
            modelId={selected.modelId}
            modelConfig={selected.config}
          />
        ) : (
          <div className="bmp__empty">
            <p className="bmp__empty-title">Select a bookmark to begin</p>
            <p className="bmp__empty-hint">
              Then pick an AI model — tank overflow asks for tank corners,
              geo-fencing asks for zones, fall detection and PPE detection
              run immediately.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
