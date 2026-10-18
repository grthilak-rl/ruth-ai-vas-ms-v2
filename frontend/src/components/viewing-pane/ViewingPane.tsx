import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { LiveVideoPlayer } from '../video/LiveVideoPlayer';
import { useDevicesQuery, deviceDisplayName } from '../../state';
import type { Device } from '../../state';
import { activeModelIds } from '../../state/api/devices.api';
import type { ModelConfig } from '../../types/geofencing';
import { getSelectedCameraIds } from '../../utils/cameraGridPreferences';
import {
  type CellAssignments,
  PANE_GRID_SIZES,
  assignCell,
  getCellAssignments,
  getPaneTileCount,
  presetSizeOf,
  setCellAssignments,
} from '../../utils/viewingPanePreferences';
import { visibleCellKeys } from '../../utils/viewingPaneLayout';
import { GridLayoutPicker } from './GridLayoutPicker';
import { usePaneLayout } from './usePaneLayout';
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

  // Follows layout changes made on Camera Monitoring while this window is open.
  const [layout, handleLayoutChange] = usePaneLayout();
  const [assignments, setAssignmentsState] = useState<CellAssignments>(getCellAssignments);
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

  const presetSize = presetSizeOf(layout);
  const cellKeys = useMemo(() => visibleCellKeys(layout), [layout]);

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
  // Functional update so the handler is stable and memoised tiles don't
  // re-render every time some other tile's assignment changes.
  const handleAssign = useCallback((key: string, cameraId: string | null) => {
    setAssignmentsState((current) => {
      const next = assignCell(current, key, cameraId);
      setCellAssignments(next);
      return next;
    });
  }, []);

  // Layout changes never trim assignments: positions the new layout hides
  // keep their cameras, so shrinking and growing back restores the wall.

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

  /**
   * Cameras visible on the wall — offered as disabled elsewhere, so one feed
   * can't occupy two tiles. A camera parked in a position the current layout
   * hides stays offered; picking it moves it here (see assignCell).
   */
  const assignedCameraIds = useMemo(() => {
    const ids = new Set<string>();
    for (const key of cellKeys) {
      const id = assignments[key];
      if (id) ids.add(id);
    }
    return ids;
  }, [assignments, cellKeys]);

  // Presets keep the aspect-locked 16:9 grid; custom layouts fill the screen
  // and letterbox inside each tile instead.
  const gridClass = presetSize
    ? `viewing-pane__grid viewing-pane__grid--${presetSize}`
    : 'viewing-pane__grid viewing-pane__grid--custom';
  const gridStyle = presetSize
    ? undefined
    : { gridTemplate: `repeat(${layout.rows}, 1fr) / repeat(${layout.cols}, 1fr)` };

  return (
    <div className={`viewing-pane ${controlsVisible ? '' : 'viewing-pane--idle'}`}>
      <div className={gridClass} style={gridStyle}>
        {cellKeys.map((key, tileIndex) => {
          const cameraId = assignments[key];
          const camera = cameraId ? camerasById.get(cameraId) : undefined;

          if (!camera) {
            return (
              <div
                key={`cell:${key}`}
                className="viewing-pane__tile viewing-pane__tile--empty"
              >
                <select
                  className="viewing-pane__tile-picker"
                  value=""
                  aria-label={`Assign a camera to tile ${tileIndex + 1}`}
                  onChange={(e) => handleAssign(key, e.target.value || null)}
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
            // Keyed by camera, not position: a camera that stays on screen
            // through a layout change keeps its WebRTC connection.
            <ViewingPaneTile
              key={`cam:${camera.id}`}
              camera={camera}
              cellKey={key}
              tileIndex={tileIndex}
              onAssign={handleAssign}
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
                size === presetSize ? 'viewing-pane__toolbar-button--active' : ''
              }`}
              onClick={() => handleLayoutChange({ rows: size, cols: size })}
              aria-pressed={size === presetSize}
            >
              {getPaneTileCount(size)}
            </button>
          ))}
          <GridLayoutPicker
            layout={layout}
            fitCount={availableCameras.length}
            onSelect={handleLayoutChange}
          />
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
  cellKey: string;
  tileIndex: number;
  onAssign: (cellKey: string, cameraId: string | null) => void;
}

const ViewingPaneTile = memo(function ViewingPaneTile({
  camera,
  cellKey,
  tileIndex,
  onAssign,
}: ViewingPaneTileProps) {
  const label = deviceDisplayName(camera);
  const streaming = camera.streaming;

  // Which model is running is read from the camera's own backend state, not
  // from the monitoring page's session-scoped toggles. That state is what
  // decides whether the backend is producing detections at all, so it is the
  // right thing to gate the overlay on — and it means the wall shows overlays
  // correctly even when opened in a fresh browser that never touched a toggle.
  const activeModels = activeModelIds(streaming);
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
        isDetectionActive={activeModels.length > 0}
        showOverlays={activeModels.length > 0}
        enabledModels={activeModels}
        isTankOverflowEnabled={activeModels.includes('tank_overflow_monitoring')}
        isChaneTankEnabled={activeModels.includes('chane_tank_monitor')}
        isGeofencingEnabled={activeModels.includes('geo_fencing')}
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
        onClick={() => onAssign(cellKey, null)}
        aria-label={`Clear ${label} from tile ${tileIndex + 1}`}
        title={`Clear ${label}`}
      >
        ✕
      </button>
    </div>
  );
});
