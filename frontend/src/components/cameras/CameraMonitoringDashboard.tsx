import { useState, useEffect, useMemo, useCallback } from 'react';
import { useQueries, useQueryClient } from '@tanstack/react-query';
import { CameraGridSelector } from './CameraGridSelector';
import { CameraSelectorDropdown } from './CameraSelectorDropdown';
import { ShiftConfigDropdown } from './ShiftConfigDropdown';
import { ShiftIndicator } from './ShiftIndicator';
import { CameraGridCell } from './CameraGridCell';
import { useShiftViolationCountsQuery } from '../../state/hooks/useShiftQuery';
import type { AIModel } from './AIModelSelector';
import type { Device } from '../../state';
import type { ModelConfig } from '../../types/geofencing';
import {
  type GridSize,
  getGridSize,
  setGridSize,
  getSelectedCameraIds,
  setSelectedCameraIds,
  autoSelectCameras,
  getMaxCameras,
} from '../../utils/cameraGridPreferences';
import {
  type PaneGridSize,
  PANE_GRID_SIZES,
  getPaneGridSize,
  getPaneTileCount,
  setPaneGridSize,
} from '../../utils/viewingPanePreferences';
import { fetchModelsStatus, type ModelStatusInfo } from '../../state/api/models.api';
import { type CameraModelsResponse } from '../../state/api/devices.api';
import { ApiError } from '../../state/api/errors';
import { queryKeys } from '../../state/queryKeys';
import {
  cameraModelsQueryOptions,
  useAddCameraModelMutation,
  useUpdateCameraModelMutation,
  useRemoveCameraModelMutation,
} from '../../state/hooks/useDevicesQuery';
import {
  configsFor,
  enabledModelIdsFor,
  executeToggle,
  pickerModels,
  planToggle,
  type ToggleAction,
} from './pickerState';
import { useDeviceSync } from '../../state/hooks/useDeviceSync';
import './CameraMonitoringDashboard.css';

/**
 * CameraMonitoringDashboard Component
 *
 * Consolidated multi-camera monitoring dashboard that replaces the two-page architecture.
 * Per F7:
 * - Configurable grid layouts (1×1 through 5×5)
 * - Camera selector dropdown for multi-select
 * - Per-camera AI model toggles
 * - All state variations (loading, connecting, live, offline, error, degraded)
 * - Grid size and selected cameras persist in localStorage
 * - AI model toggles show the server's state: each one adds or removes one
 *   model through /devices/{id}/models (see pickerState.ts)
 *
 * States per F7 §8:
 * - Loading: Initial dashboard load
 * - Empty: No cameras configured
 * - Error: Dashboard API failure
 */

interface CameraMonitoringDashboardProps {
  cameras: Device[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}

/** Operator-facing text for a failed picker change. */
function pickerErrorMessage(kind: ToggleAction['kind'], modelId: string, error: unknown): string {
  const verb = kind === 'add' ? 'start' : kind === 'remove' ? 'stop' : 'update';
  const reason = error instanceof ApiError ? error.message : 'unexpected error';
  return `Could not ${verb} ${modelId}: ${reason}`;
}

export function CameraMonitoringDashboard({
  cameras,
  isLoading,
  isError,
  onRetry,
}: CameraMonitoringDashboardProps) {
  // Grid size state
  const [gridSize, setGridSizeState] = useState<GridSize>(getGridSize());

  // Tile count the Viewing Pane will open with. Stored in the pane's own
  // preferences so choosing it here and opening the wall agree, and so the
  // wall keeps it across reloads.
  const [paneGridSize, setPaneGridSizeState] = useState<PaneGridSize>(getPaneGridSize);

  // Selected cameras state
  const [selectedCameraIds, setSelectedCameraIdsState] = useState<string[]>(() =>
    getSelectedCameraIds()
  );

  // Available AI models from backend
  const [availableModels, setAvailableModels] = useState<ModelStatusInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);

  // Pull any cameras added in VAS since Ruth's backend last synced, so the
  // grid and Camera Selector reflect the VAS devices page without a
  // ruth-ai-backend restart. Non-blocking — the dashboard renders from the
  // cached device list and updates in place when the sync lands. syncNow is
  // throttled and deduplicated, so a remount (or the selector opening right
  // after) is a no-op rather than a second VAS round-trip.
  const { syncNow } = useDeviceSync();
  useEffect(() => {
    void syncNow();
  }, [syncNow]);

  // Fetch available models from backend
  useEffect(() => {
    async function loadModels() {
      try {
        setModelsLoading(true);
        const response = await fetchModelsStatus();
        setAvailableModels(response.models);
      } catch (error) {
        console.error('[CameraMonitoring] Failed to fetch models:', error);
        setAvailableModels([]);
      } finally {
        setModelsLoading(false);
      }
    }
    loadModels();
  }, []);

  // Seed the selection on first run. autoSelectCameras leaves an existing
  // selection alone (beyond trimming to grid capacity), so this can no longer
  // drop a saved camera that happens to be missing from the current list —
  // which is what silently erased selections on refresh, since the result is
  // persisted. Availability is handled at render time by `selectedCameras`.
  useEffect(() => {
    if (cameras.length > 0) {
      const cameraIds = cameras.map((c) => c.id);
      const autoSelected = autoSelectCameras(cameraIds, gridSize, selectedCameraIds);
      if (JSON.stringify(autoSelected) !== JSON.stringify(selectedCameraIds)) {
        setSelectedCameraIdsState(autoSelected);
        setSelectedCameraIds(autoSelected);
      }
    }
  }, [cameras, gridSize]); // Intentionally not including selectedCameraIds to avoid infinite loop

  // Handle grid size change
  const handleGridSizeChange = (size: GridSize) => {
    setGridSizeState(size);
    setGridSize(size);

    // Trim selected cameras if new grid is smaller
    const maxCameras = getMaxCameras(size);
    if (selectedCameraIds.length > maxCameras) {
      const trimmed = selectedCameraIds.slice(0, maxCameras);
      setSelectedCameraIdsState(trimmed);
      setSelectedCameraIds(trimmed);
    }
  };

  // Handle camera selection change
  const handleCameraSelectionChange = (cameraIds: string[]) => {
    setSelectedCameraIdsState(cameraIds);
    setSelectedCameraIds(cameraIds);
  };

  // Get selected cameras
  const selectedCameras = useMemo(() => {
    return cameras.filter((camera) => selectedCameraIds.includes(camera.id));
  }, [cameras, selectedCameraIds]);

  // What runs on each camera comes from the server. Cameras the devices list
  // reports as AI-enabled fetch their model list (configs included);
  // others read whatever the cache holds, which the picker fills when it
  // opens. Mutations write their response straight into this cache.
  const queryClient = useQueryClient();
  const cameraModelQueries = useQueries({
    queries: selectedCameras.map((camera) =>
      cameraModelsQueryOptions(camera.id, camera.streaming.ai_enabled)
    ),
  });
  const serverModels = useMemo(() => {
    const byCamera: Record<string, CameraModelsResponse | undefined> = {};
    selectedCameras.forEach((camera, i) => {
      byCamera[camera.id] = cameraModelQueries[i]?.data;
    });
    return byCamera;
  }, [selectedCameras, cameraModelQueries]);

  const runningModelIds = useCallback(
    (camera: Device): string[] => enabledModelIdsFor(camera.streaming, serverModels[camera.id]),
    [serverModels]
  );
  const cameraConfigs = useCallback(
    (camera: Device): Record<string, ModelConfig> => configsFor(camera.streaming, serverModels[camera.id]),
    [serverModels]
  );

  // One in-flight change and the last error, per camera. No optimistic
  // flip: a row shows "Applying" until the server's answer lands.
  const [pendingModel, setPendingModel] = useState<Record<string, string | undefined>>({});
  const [pickerErrors, setPickerErrors] = useState<Record<string, string | undefined>>({});

  // Each writes its response (the camera's model list) into the cache and
  // invalidates queryKeys.devices.all, so tiles, overlays and the picker
  // follow at once rather than on the 120s devices poll.
  const addModelMutation = useAddCameraModelMutation();
  const updateModelMutation = useUpdateCameraModelMutation();
  const removeModelMutation = useRemoveCameraModelMutation();

  // Handle AI model toggle: one call on /devices/{id}/models per change.
  const handleModelToggle = useCallback(async (cameraId: string, modelId: string, enabled: boolean, config?: ModelConfig) => {
    const camera = cameras.find((c) => c.id === cameraId);
    if (!camera || pendingModel[cameraId]) return;

    const action = planToggle(enabled, modelId, runningModelIds(camera), config);
    if (action.kind === 'noop') return;

    setPendingModel((prev) => ({ ...prev, [cameraId]: modelId }));
    setPickerErrors((prev) => ({ ...prev, [cameraId]: undefined }));
    try {
      await executeToggle(action, {
        add: (entry) => addModelMutation.mutateAsync({ deviceId: cameraId, entry }),
        update: (changes) => updateModelMutation.mutateAsync({ deviceId: cameraId, modelId, changes }),
        remove: () => removeModelMutation.mutateAsync({ deviceId: cameraId, modelId }),
      });
    } catch (error) {
      console.error(`[CameraMonitoring] ${action.kind} ${modelId} failed:`, error);
      setPickerErrors((prev) => ({ ...prev, [cameraId]: pickerErrorMessage(action.kind, modelId, error) }));
      // Whatever happened, show what the server has now.
      void queryClient.invalidateQueries({ queryKey: queryKeys.devices.models(cameraId) });
    } finally {
      setPendingModel((prev) => ({ ...prev, [cameraId]: undefined }));
    }
  }, [cameras, pendingModel, runningModelIds, addModelMutation, updateModelMutation, removeModelMutation, queryClient]);

  // Refresh one camera's server state when its picker opens: another
  // operator may have changed it since the last fetch.
  const handlePickerOpen = useCallback((cameraId: string) => {
    void queryClient.fetchQuery(cameraModelsQueryOptions(cameraId));
  }, [queryClient]);

  // chane_tank_monitor: operator confirmed a clicked ROI circle. Merge it into
  // that model's config and persist it (so the headless inference loop picks
  // it up). The cached list is updated first so the overlay uses the new ROI
  // at once; a failure refetches the server's version.
  const handleRoiConfirm = useCallback(async (
    cameraId: string,
    modelId: string,
    roiCircle: { cx: number; cy: number; r: number },
  ) => {
    const camera = cameras.find((c) => c.id === cameraId);
    if (!camera) return;
    const merged: ModelConfig = {
      ...(cameraConfigs(camera)[modelId] || {}),
      roi_circle: roiCircle,
    };
    queryClient.setQueryData<CameraModelsResponse>(queryKeys.devices.models(cameraId), (prev) =>
      prev
        ? { ...prev, models: prev.models.map((m) => (m.model_id === modelId ? { ...m, config: merged } : m)) }
        : prev
    );
    try {
      await updateModelMutation.mutateAsync({ deviceId: cameraId, modelId, changes: { config: merged } });
    } catch (error) {
      console.error('[CameraMonitoring] Failed to persist ROI config:', error);
      setPickerErrors((prev) => ({ ...prev, [cameraId]: pickerErrorMessage('update', modelId, error) }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.devices.models(cameraId) });
    }
  }, [cameras, cameraConfigs, queryClient, updateModelMutation]);

  // Handle fullscreen
  const handleFullscreen = useCallback(
    (cameraId: string) => {
      window.open(`/cameras/fullscreen/${cameraId}`, '_blank');
    },
    []
  );

  // Unreviewed violations raised during the current shift, per camera.
  // One request covers every tile on the grid; the backend owns both the
  // shift window and the counting, so the number on a card and the shift
  // named in the toolbar always describe the same window.
  const shiftCountsQuery = useShiftViolationCountsQuery(selectedCameraIds);
  const violationCounts = shiftCountsQuery.data?.counts;

  // Get AI models for a camera: every healthy or degraded runtime model,
  // ticked when the server says it runs on this camera.
  const getAIModelsForCamera = useCallback(
    (camera: Device): AIModel[] => {
      if (modelsLoading || availableModels.length === 0) {
        return [];
      }
      return pickerModels(availableModels, runningModelIds(camera), pendingModel[camera.id]);
    },
    [availableModels, modelsLoading, runningModelIds, pendingModel]
  );

  // Get detection status for a camera
  const getDetectionStatusForCamera = useCallback(
    (camera: Device): 'active' | 'degraded' | 'unavailable' | 'plain' => {
      const models = getAIModelsForCamera(camera);
      const activeModels = models.filter((m) => m.state === 'active');
      const degradedModels = models.filter((m) => m.state === 'degraded');

      if (activeModels.length > 0) return 'active';
      if (degradedModels.length > 0) return 'degraded';
      if (models.some((m) => m.state === 'unavailable')) return 'unavailable';
      return 'plain';
    },
    [getAIModelsForCamera]
  );

  // Get camera status
  const getCameraStatus = (camera: Device): 'live' | 'offline' | 'connecting' | 'error' => {
    return camera.is_active ? 'live' : 'offline';
  };

  // Generate empty slots
  const gridCells = useMemo(() => {
    const maxCameras = getMaxCameras(gridSize);
    const cells: Array<{ type: 'camera'; camera: Device } | { type: 'empty' }> = [];

    // Add selected cameras
    selectedCameras.forEach((camera) => {
      cells.push({ type: 'camera', camera });
    });

    // Add empty slots
    for (let i = selectedCameras.length; i < maxCameras; i++) {
      cells.push({ type: 'empty' });
    }

    return cells;
  }, [selectedCameras, gridSize]);

  // Open the wall in its OWN window, not this tab.
  //
  // The operator runs two displays: the management view on the workstation and
  // the wall on a monitoring TV. Navigating in-tab would replace the view they
  // are working in, so this opens a separate window that can be dragged to the
  // TV and fullscreened there while this tab stays on the monitoring page.
  //
  // The window is NAMED, so clicking again focuses the existing wall rather
  // than spawning a second copy — a second copy would mean a second set of
  // WebRTC consumers decoding the same feeds. popup=yes drops the tab/address
  // bar so it behaves like a display surface; the route already renders
  // outside AppShell, so there is no app chrome either.
  const handleOpenViewingPane = useCallback(() => {
    const features = [
      'popup=yes',
      'noopener=no',
      'width=1280',
      'height=720',
      'menubar=no',
      'toolbar=no',
      'location=no',
      'status=no',
      'resizable=yes',
      'scrollbars=no',
    ].join(',');

    const paneWindow = window.open('/cameras/viewing-pane', 'ruth-ai-viewing-pane', features);

    if (paneWindow) {
      // Already-open wall: bring it forward instead of leaving the operator
      // wondering why the click did nothing.
      paneWindow.focus();
    } else {
      console.warn(
        '[CameraMonitoring] Viewing Pane window was blocked. Allow pop-ups for this site.'
      );
    }
  }, []);

  // Viewing Pane entry. Shared by the loading / empty / main toolbars so the
  // control is in the same place regardless of dashboard state.
  //
  // A button rather than a <Link>: this must open a separate window, not
  // navigate this tab. The route is still a real bookmarkable URL for kiosk
  // use — see handleOpenViewingPane.
  const viewingPaneControls = (
    <div className="camera-monitoring-dashboard__viewing-pane-controls">
      <span className="camera-monitoring-dashboard__viewing-pane-label">Viewing Pane:</span>
      <div
        className="camera-monitoring-dashboard__viewing-pane-tiles"
        role="group"
        aria-label="Viewing pane tile count"
      >
        {PANE_GRID_SIZES.map((size) => (
          <button
            key={size}
            type="button"
            className={`camera-monitoring-dashboard__viewing-pane-tile-button ${
              size === paneGridSize
                ? 'camera-monitoring-dashboard__viewing-pane-tile-button--active'
                : ''
            }`}
            onClick={() => {
              setPaneGridSizeState(size);
              setPaneGridSize(size);
            }}
            aria-pressed={size === paneGridSize}
            title={`${size}x${size} (${getPaneTileCount(size)} tiles)`}
          >
            {getPaneTileCount(size)}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="camera-monitoring-dashboard__viewing-pane-button"
        onClick={handleOpenViewingPane}
        title="Opens in a separate window you can move to the monitoring TV"
      >
        ⛶ Open Viewing Pane
      </button>
    </div>
  );

  // Loading state
  if (isLoading) {
    return (
      <div className="camera-monitoring-dashboard">
        <div className="camera-monitoring-dashboard__toolbar">
          <CameraGridSelector currentSize={gridSize} onSizeChange={handleGridSizeChange} />
          <CameraSelectorDropdown
            cameras={cameras}
            selectedCameraIds={selectedCameraIds}
            gridSize={gridSize}
            onSelectionChange={handleCameraSelectionChange}
          />
          <ShiftConfigDropdown />
          <ShiftIndicator />
          {viewingPaneControls}
        </div>
        <div className={`camera-monitoring-dashboard__grid camera-monitoring-dashboard__grid--${gridSize}x${gridSize}`}>
          {Array.from({ length: getMaxCameras(gridSize) }).map((_, index) => (
            <div key={index} className="camera-monitoring-dashboard__skeleton" />
          ))}
        </div>
      </div>
    );
  }

  // Error state
  if (isError) {
    return (
      <div className="camera-monitoring-dashboard">
        <div className="camera-monitoring-dashboard__error-state">
          <div className="camera-monitoring-dashboard__error-content">
            <p className="camera-monitoring-dashboard__error-title">⚠ Unable to load cameras</p>
            <p className="camera-monitoring-dashboard__error-message">
              Could not retrieve camera list. This may be a temporary issue.
            </p>
            <button
              type="button"
              className="camera-monitoring-dashboard__retry-button"
              onClick={onRetry}
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Empty state
  if (cameras.length === 0) {
    return (
      <div className="camera-monitoring-dashboard">
        <div className="camera-monitoring-dashboard__toolbar">
          <CameraGridSelector currentSize={gridSize} onSizeChange={handleGridSizeChange} />
          <CameraSelectorDropdown
            cameras={cameras}
            selectedCameraIds={selectedCameraIds}
            gridSize={gridSize}
            onSelectionChange={handleCameraSelectionChange}
          />
          <ShiftConfigDropdown />
          <ShiftIndicator />
          {viewingPaneControls}
        </div>
        <div className="camera-monitoring-dashboard__empty-state">
          <div className="camera-monitoring-dashboard__empty-content">
            <p className="camera-monitoring-dashboard__empty-title">No cameras configured</p>
            <p className="camera-monitoring-dashboard__empty-message">
              Contact your admin to add cameras to the system.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Main state
  return (
    <div className="camera-monitoring-dashboard">
      <div className="camera-monitoring-dashboard__toolbar">
        <CameraGridSelector currentSize={gridSize} onSizeChange={handleGridSizeChange} />
        <CameraSelectorDropdown
          cameras={cameras}
          selectedCameraIds={selectedCameraIds}
          gridSize={gridSize}
          onSelectionChange={handleCameraSelectionChange}
        />
        <ShiftConfigDropdown />
        <ShiftIndicator />
        {viewingPaneControls}
      </div>

      <div
        className={`camera-monitoring-dashboard__grid camera-monitoring-dashboard__grid--${gridSize}x${gridSize}`}
      >
        {gridCells.map((cell, index) => {
          if (cell.type !== 'camera') {
            return (
              <div key={`empty-${index}`} className="camera-monitoring-dashboard__empty-cell">
                <div className="camera-monitoring-dashboard__empty-cell-icon">+</div>
                <p className="camera-monitoring-dashboard__empty-cell-text">Add Camera</p>
                <p className="camera-monitoring-dashboard__empty-cell-subtext">
                  Click to select from available cameras
                </p>
              </div>
            );
          }

          // Auto-connect only cameras the backend reports as live.
          // Stagger by the camera's position among selected cameras (not
          // the grid index, so empty slots don't add gaps): mirrors VAS's
          // ~500ms per-camera spacing to avoid an N-camera WebRTC burst.
          const cameraIndex = selectedCameras.findIndex(c => c.id === cell.camera.id);
          const shouldAutoConnect = cell.camera.streaming.video_live === true;
          const autoConnectDelayMs = cameraIndex >= 0 ? cameraIndex * 500 : 0;

          return (
            <CameraGridCell
              key={cell.camera.id}
              camera={cell.camera}
              status={getCameraStatus(cell.camera)}
              detectionStatus={getDetectionStatusForCamera(cell.camera)}
              aiModels={getAIModelsForCamera(cell.camera)}
              violationCount={violationCounts?.[cell.camera.id]}
              onModelToggle={handleModelToggle}
              onRoiConfirm={handleRoiConfirm}
              modelConfigs={cameraConfigs(cell.camera)}
              onFullscreen={handleFullscreen}
              shouldAutoConnect={shouldAutoConnect}
              autoConnectDelayMs={autoConnectDelayMs}
              runningModelIds={runningModelIds(cell.camera)}
              onPickerOpen={handlePickerOpen}
              pickerError={pickerErrors[cell.camera.id]}
            />
          );
        })}
      </div>
    </div>
  );
}