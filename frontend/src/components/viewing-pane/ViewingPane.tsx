import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { LiveVideoPlayer } from '../video/LiveVideoPlayer';
import { useDevicesQuery, deviceDisplayName } from '../../state';
import type { Device } from '../../state';
import type { ModelConfig } from '../../types/geofencing';
import { getSelectedCameraIds } from '../../utils/cameraGridPreferences';
import {
  type PaneGridSize,
  type TileAssignments,
  PANE_GRID_SIZES,
  assignTile,
  getPaneGridSize,
  getPaneTileCount,
  getTileAssignments,
  setPaneGridSize,
  setTileAssignments,
  trimAssignmentsToGrid,
} from '../../utils/viewingPanePreferences';
import './ViewingPane.css';

/**
 * How long the controls linger after the last input before fading away.
 *
 * Long enough to move the pointer from one control to another without the
 * toolbar vanishing mid-reach, short enough that the wall is clean again
 * moments after someone walks away from it.
 */
const CONTROLS_IDLE_MS = 2500;

/**
 * ViewingPane — fullscreen, view-only video wall.
 *
 * A passive display: no snapshot, no bookmark, no playback controls. The only
 * interactions are assigning a camera to a tile and clearing it, and both are
 * hidden until someone reaches for them.
 *
 * It is a deliberately LIGHT consumer. Tiles decode video and draw boxes read
 * from the shared per-camera detection source; none of them runs inference.
 * That is what makes 16 tiles viable — before detections moved to the backend,
 * a 16-tile wall meant 16 JPEG encodes and 16 uploads per second competing
 * with compositing on the main thread.
 */
export function ViewingPane() {
  const { data: devicesData } = useDevicesQuery();
  const cameras = useMemo(() => devicesData?.items ?? [], [devicesData]);

  const [gridSize, setGridSizeState] = useState<PaneGridSize>(getPaneGridSize);
  const [assignments, setAssignmentsState] = useState<TileAssignments>(getTileAssignments);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Transient controls, the standard video-player pattern: any input reveals
  // them, then they fade after a period of inactivity.
  //
  // This replaces a CSS :hover rule on the pane itself, which could never
  // work — the pane is the whole screen, so "hovering the pane" is true the
  // entire time the pointer is anywhere on the display, and the toolbar
  // simply never went away. It sat permanently over the top-row tiles'
  // display_name labels.
  const [controlsVisible, setControlsVisible] = useState(false);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Set while the pointer rests on the toolbar, so the controls can't fade
  // out from under someone who is actively reaching for a button.
  const pointerOverControlsRef = useRef(false);

  const clearHideTimer = useCallback(() => {
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }, []);

  const revealControls = useCallback(() => {
    setControlsVisible(true);
    clearHideTimer();
    if (pointerOverControlsRef.current) return;
    hideTimerRef.current = setTimeout(() => setControlsVisible(false), CONTROLS_IDLE_MS);
  }, [clearHideTimer]);

  // Listen on window rather than the pane element so activity is caught even
  // when the pointer is over a tile's own controls, and so clicking the
  // fullscreen button counts as activity — it restarts the timer instead of
  // leaving the toolbar stuck on.
  useEffect(() => {
    const onActivity = () => revealControls();
    const events: Array<keyof WindowEventMap> = [
      'mousemove',
      'mousedown',
      'keydown',
      'touchstart',
      'wheel',
    ];
    for (const event of events) window.addEventListener(event, onActivity, { passive: true });
    return () => {
      for (const event of events) window.removeEventListener(event, onActivity);
      clearHideTimer();
    };
  }, [revealControls, clearHideTimer]);

  const tileCount = getPaneTileCount(gridSize);

  /**
   * Cameras offered in the tile dropdowns: the selection made on the
   * monitoring page. The wall shows a subset of what the operator is already
   * working with, rather than the whole estate.
   */
  const selectedCameraIds = useMemo(() => getSelectedCameraIds(), []);
  const availableCameras = useMemo(() => {
    const selected = new Set(selectedCameraIds);
    return cameras
      .filter((camera) => selected.has(camera.id))
      .sort((a, b) => deviceDisplayName(a).localeCompare(deviceDisplayName(b)));
  }, [cameras, selectedCameraIds]);

  const camerasById = useMemo(() => {
    const map = new Map<string, Device>();
    for (const camera of cameras) map.set(camera.id, camera);
    return map;
  }, [cameras]);

  // Persist on every change: the display must survive a power cut with no
  // operator present to restore it.
  const updateAssignments = useCallback((next: TileAssignments) => {
    setAssignmentsState(next);
    setTileAssignments(next);
  }, []);

  const handleAssign = useCallback(
    (tileIndex: number, cameraId: string | null) => {
      updateAssignments(assignTile(assignments, tileIndex, cameraId));
    },
    [assignments, updateAssignments]
  );

  const handleGridSizeChange = useCallback(
    (size: PaneGridSize) => {
      setGridSizeState(size);
      setPaneGridSize(size);
      // Trim only when shrinking, and only here — never on load — so viewing a
      // 4x4 wall at 2x2 for a moment doesn't discard twelve assignments.
      if (getPaneTileCount(size) < Object.keys(assignments).length) {
        updateAssignments(trimAssignmentsToGrid(assignments, size));
      }
    },
    [assignments, updateAssignments]
  );

  // Fullscreen. Tracked via the fullscreenchange event rather than assumed
  // from our own toggle, so pressing Escape (or F11) keeps the button honest.
  const toggleFullscreen = useCallback(async () => {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await document.documentElement.requestFullscreen();
      }
    } catch (error) {
      console.warn('[ViewingPane] Fullscreen toggle failed:', error);
    }
  }, []);

  useEffect(() => {
    const onChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', onChange);
    onChange();
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  /** Cameras already on the wall — offered as disabled elsewhere, so one feed can't occupy two tiles. */
  const assignedCameraIds = useMemo(() => new Set(Object.values(assignments)), [assignments]);

  return (
    <div className={`viewing-pane ${controlsVisible ? '' : 'viewing-pane--idle'}`}>
      <div className={`viewing-pane__grid viewing-pane__grid--${gridSize}`}>
        {Array.from({ length: tileCount }).map((_, tileIndex) => {
          const cameraId = assignments[tileIndex];
          const camera = cameraId ? camerasById.get(cameraId) : undefined;

          if (!camera) {
            return (
              <div
                key={tileIndex}
                className="viewing-pane__tile viewing-pane__tile--empty"
              >
                <select
                  className="viewing-pane__tile-picker"
                  value=""
                  aria-label={`Assign a camera to tile ${tileIndex + 1}`}
                  onChange={(e) => handleAssign(tileIndex, e.target.value || null)}
                >
                  <option value="">Select camera…</option>
                  {availableCameras.map((option) => (
                    <option
                      key={option.id}
                      value={option.id}
                      disabled={assignedCameraIds.has(option.id)}
                    >
                      {deviceDisplayName(option)}
                      {assignedCameraIds.has(option.id) ? ' (on wall)' : ''}
                    </option>
                  ))}
                </select>
                {availableCameras.length === 0 && (
                  <span className="viewing-pane__tile-empty-hint">
                    Select cameras on the monitoring page first
                  </span>
                )}
              </div>
            );
          }

          return (
            <ViewingPaneTile
              key={tileIndex}
              camera={camera}
              tileIndex={tileIndex}
              onClear={() => handleAssign(tileIndex, null)}
            />
          );
        })}
      </div>

      <div
        className={`viewing-pane__toolbar ${
          controlsVisible ? 'viewing-pane__toolbar--visible' : ''
        }`}
        onMouseEnter={() => {
          pointerOverControlsRef.current = true;
          clearHideTimer();
          setControlsVisible(true);
        }}
        onMouseLeave={() => {
          pointerOverControlsRef.current = false;
          revealControls();
        }}
      >
        <span className="viewing-pane__toolbar-label">Tiles</span>
        <div className="viewing-pane__toolbar-group" role="group" aria-label="Tile count">
          {PANE_GRID_SIZES.map((size) => (
            <button
              key={size}
              type="button"
              className={`viewing-pane__toolbar-button ${
                size === gridSize ? 'viewing-pane__toolbar-button--active' : ''
              }`}
              onClick={() => handleGridSizeChange(size)}
              aria-pressed={size === gridSize}
            >
              {getPaneTileCount(size)}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="viewing-pane__toolbar-button"
          onClick={toggleFullscreen}
        >
          {isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
        </button>
      </div>
    </div>
  );
}

interface ViewingPaneTileProps {
  camera: Device;
  tileIndex: number;
  onClear: () => void;
}

function ViewingPaneTile({ camera, tileIndex, onClear }: ViewingPaneTileProps) {
  const label = deviceDisplayName(camera);
  const streaming = camera.streaming;

  // Which model is running is read from the camera's own backend state, not
  // from the monitoring page's session-scoped toggles. That state is what
  // decides whether the backend is producing detections at all, so it is the
  // right thing to gate the overlay on — and it means the wall shows overlays
  // correctly even when opened in a fresh browser that never touched a toggle.
  const activeModelId = streaming.ai_enabled ? streaming.model_id : null;
  const modelConfig = (streaming.model_config ?? undefined) as ModelConfig | undefined;

  return (
    <div className="viewing-pane__tile">
      <LiveVideoPlayer
        deviceId={camera.id}
        deviceName={label}
        isAvailable={streaming.video_live === true}
        chromeless
        shouldAutoConnect={streaming.video_live === true}
        // Stagger by tile position so 16 tiles don't open 16 WebRTC peers in
        // the same tick — the same 500ms spacing the monitoring grid uses.
        autoConnectDelayMs={tileIndex * 500}
        isDetectionActive={Boolean(activeModelId)}
        showOverlays={Boolean(activeModelId)}
        isFallDetectionEnabled={activeModelId === 'fall_detection'}
        isPPEDetectionEnabled={activeModelId === 'ppe_detection'}
        isTankOverflowEnabled={activeModelId === 'tank_overflow_monitoring'}
        isChaneTankEnabled={activeModelId === 'chane_tank_monitor'}
        isGeofencingEnabled={activeModelId === 'geo_fencing'}
        tankCorners={modelConfig?.tank_corners}
        chaneTankRoiCircle={modelConfig?.roi_circle}
        geofenceZones={modelConfig?.zones}
        // Deliberately no onChaneRoiConfirm: the wall is view-only, so the ROI
        // picker stays out of reach even for chane cameras.
      />

      <span className="viewing-pane__tile-label">{label}</span>

      <button
        type="button"
        className="viewing-pane__tile-clear"
        onClick={onClear}
        aria-label={`Clear ${label} from tile ${tileIndex + 1}`}
        title={`Clear ${label}`}
      >
        ✕
      </button>
    </div>
  );
}
