import { useMemo } from 'react';
import { LiveVideoPlayer } from '../video/LiveVideoPlayer';
import { AIModelSelector, type AIModel } from './AIModelSelector';
import { deviceDisplayName } from '../../state';
import { CameraNamingEditor } from './CameraNamingEditor';
import type { Device } from '../../state';
import { activeModelIds } from '../../state/api/devices.api';
import type { ModelConfig } from '../../types/geofencing';
import './CameraGridCell.css';

/**
 * CameraGridCell Component
 *
 * Individual camera cell in the grid with video, controls, and status.
 * Per F7 §4.2.3:
 * - Video area with detection overlays
 * - Status bar with camera name, detection status and status indicator
 * - AI controls with model selector, fullscreen button and violation count
 *
 * States per F7 §8:
 * - Loading: Connecting state
 * - Live: Video playing with LIVE indicator
 * - Offline: Camera offline message
 * - Error: Video error state with retry
 * - AI Degraded: Video plays, AI has issues
 */

type CameraStatus = 'live' | 'offline' | 'connecting' | 'error';
type DetectionStatus = 'active' | 'degraded' | 'unavailable' | 'plain';

interface CameraGridCellProps {
  camera: Device;
  status: CameraStatus;
  detectionStatus: DetectionStatus;
  aiModels: AIModel[];
  violationCount?: number;
  onModelToggle: (cameraId: string, modelId: string, enabled: boolean, config?: ModelConfig) => void;
  /** chane_tank_monitor: commit an operator-clicked ROI circle for this camera. */
  onRoiConfirm?: (cameraId: string, modelId: string, roiCircle: { cx: number; cy: number; r: number }) => void;
  modelConfigs?: Record<string, ModelConfig>;
  onFullscreen: (cameraId: string) => void;
  /** When true, the underlying player connects automatically on mount. */
  shouldAutoConnect?: boolean;
  /** Stagger delay so N cells don't open WebRTC peers simultaneously. */
  autoConnectDelayMs?: number;
  /** Models running on this camera, from the server. Defaults to the
   *  devices list's streaming summary when not given. */
  runningModelIds?: readonly string[];
  /** Called when this camera's model picker opens (refresh server state). */
  onPickerOpen?: (cameraId: string) => void;
  /** The last picker change's failure for this camera. */
  pickerError?: string | null;
}

export function CameraGridCell({
  camera,
  status,
  detectionStatus,
  aiModels,
  violationCount,
  onModelToggle,
  onRoiConfirm,
  modelConfigs = {},
  onFullscreen,
  shouldAutoConnect = false,
  autoConnectDelayMs = 0,
  runningModelIds,
  onPickerOpen,
  pickerError = null,
}: CameraGridCellProps) {
  const statusIndicator = useMemo(() => {
    switch (status) {
      case 'live':
        return { icon: '●', label: 'LIVE', className: 'camera-grid-cell__status--live' };
      case 'offline':
        return { icon: '○', label: 'OFFLINE', className: 'camera-grid-cell__status--offline' };
      case 'connecting':
        return { icon: '◐', label: 'Connecting', className: 'camera-grid-cell__status--connecting' };
      case 'error':
        return { icon: '⚠', label: 'Error', className: 'camera-grid-cell__status--error' };
    }
  }, [status]);

  const detectionStatusInfo = useMemo(() => {
    switch (detectionStatus) {
      case 'active':
        return { icon: '●', label: 'Detection Active', className: 'camera-grid-cell__detection--active' };
      case 'degraded':
        return { icon: '◐', label: 'Detection Degraded', className: 'camera-grid-cell__detection--degraded' };
      case 'unavailable':
        return { icon: '✖', label: 'Detection Unavailable', className: 'camera-grid-cell__detection--unavailable' };
      case 'plain':
        return { icon: '○', label: 'Plain Video', className: 'camera-grid-cell__detection--plain' };
    }
  }, [detectionStatus]);

  const isDetectionActive = detectionStatus === 'active' || detectionStatus === 'degraded';
  const showOverlays = detectionStatus === 'active';

  // Which models run on this camera comes from the server (streaming.models),
  // not from the picker's local toggles, which can disagree with the backend.
  // The devices query is invalidated on every model add/remove, so this
  // updates immediately rather than on the 120s devices poll.
  // Keyed on the ids' content, not the array: the parent builds a new array
  // every render, and a new reference here would redraw the overlay canvas.
  const runningKey = runningModelIds?.join('\n');
  const serverModels = useMemo(
    () => (runningKey !== undefined ? (runningKey ? runningKey.split('\n') : []) : activeModelIds(camera.streaming)),
    [runningKey, camera.streaming]
  );
  const isFallDetectionActive = serverModels.includes('fall_detection');
  const isPPEDetectionActive = serverModels.includes('ppe_detection');
  const isTankOverflowActive = serverModels.includes('tank_overflow_monitoring');
  const isChaneTankActive = serverModels.includes('chane_tank_monitor');
  const isGeofencingActive = serverModels.includes('geo_fencing');

  // Get tank overflow configuration (corners)
  const tankOverflowConfig = modelConfigs['tank_overflow_monitoring'];
  const tankCorners = tankOverflowConfig?.tank_corners;

  // Get chane tank monitor configuration (optional manual circular ROI)
  const chaneTankConfig = modelConfigs['chane_tank_monitor'];
  const chaneTankRoiCircle = chaneTankConfig?.roi_circle;

  // Get geo_fencing configuration (zones)
  const geofencingConfig = modelConfigs['geo_fencing'];
  const geofenceZones = geofencingConfig?.zones;

  const handleModelToggle = (modelId: string, enabled: boolean, config?: ModelConfig) => {
    onModelToggle(camera.id, modelId, enabled, config);
  };

  const handleFullscreen = () => {
    onFullscreen(camera.id);
  };

  // Operator-facing label. VAS derives this from manway + in/out; falls
  // back to the stable identifier for cameras not yet named.
  const label = deviceDisplayName(camera);

  return (
    <div className="camera-grid-cell">
      {/* Video Area */}
      <div className="camera-grid-cell__video">
        <LiveVideoPlayer
          deviceId={camera.id}
          deviceName={label}
          isAvailable={status === 'live' || status === 'connecting'}
          isDetectionActive={isDetectionActive}
          showOverlays={showOverlays}
          isFallDetectionEnabled={isFallDetectionActive}
          isPPEDetectionEnabled={isPPEDetectionActive}
          isTankOverflowEnabled={isTankOverflowActive}
          isChaneTankEnabled={isChaneTankActive}
          isGeofencingEnabled={isGeofencingActive}
          enabledModels={serverModels}
          tankCorners={tankCorners}
          chaneTankRoiCircle={chaneTankRoiCircle}
          onChaneRoiConfirm={
            onRoiConfirm
              ? (roi) => onRoiConfirm(camera.id, 'chane_tank_monitor', roi)
              : undefined
          }
          geofenceZones={geofenceZones}
          shouldAutoConnect={shouldAutoConnect}
          autoConnectDelayMs={autoConnectDelayMs}
        />
      </div>

      {/* Status Bar */}
      <div className="camera-grid-cell__status-bar">
        <CameraNamingEditor
          deviceId={camera.id}
          identifier={camera.name}
          manway={camera.manway}
          inOut={camera.in_out}
          displayName={label}
        />
        <span className={`camera-grid-cell__detection ${detectionStatusInfo.className}`}>
          {detectionStatusInfo.icon} {detectionStatusInfo.label}
        </span>
        <span className={`camera-grid-cell__status ${statusIndicator.className}`}>
          {statusIndicator.icon} {statusIndicator.label}
        </span>
      </div>

      {/* AI Controls */}
      <div className="camera-grid-cell__controls">
        <div className="camera-grid-cell__ai-controls">
          <AIModelSelector
            cameraId={camera.id}
            cameraName={label}
            videoUrl={`/api/v1/devices/${camera.id}/snapshot`}
            models={aiModels}
            onModelToggle={handleModelToggle}
            modelConfigs={modelConfigs}
            onOpen={onPickerOpen ? () => onPickerOpen(camera.id) : undefined}
            error={pickerError}
          />
          <button
            type="button"
            className="camera-grid-cell__fullscreen-button"
            onClick={handleFullscreen}
            aria-label={`Open ${label} in fullscreen`}
            disabled={status === 'offline' || status === 'error'}
          >
            ⛶ Fullscreen
          </button>
          <span className="camera-grid-cell__violation-count">
            {violationCount !== undefined && violationCount >= 0
              ? `${violationCount} violation${violationCount !== 1 ? 's' : ''}`
              : '--'}
          </span>
        </div>
        {detectionStatus === 'degraded' && (
          <div className="camera-grid-cell__warning">
            ⚠ AI may be slower or less accurate
          </div>
        )}
      </div>
    </div>
  );
}