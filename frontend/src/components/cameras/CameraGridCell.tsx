import { useMemo } from 'react';
import { LiveVideoPlayer } from '../video/LiveVideoPlayer';
import { AIModelSelector, type AIModel } from './AIModelSelector';
import type { Device } from '../../state';
import './CameraGridCell.css';

/**
 * CameraGridCell Component
 *
 * Individual camera cell in the grid with video, controls, and status.
 * Per F7 §4.2.3:
 * - Video area with detection overlays
 * - Status bar with camera name and status indicator
 * - AI controls with model selector and detection status
 * - Actions bar with fullscreen button and violation count
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
  onModelToggle: (cameraId: string, modelId: string, enabled: boolean) => void;
  onFullscreen: (cameraId: string) => void;
}

export function CameraGridCell({
  camera,
  status,
  detectionStatus,
  aiModels,
  violationCount,
  onModelToggle,
  onFullscreen,
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

  // Determine which detection types are active
  const isFallDetectionActive = aiModels.find(m => m.id === 'fall_detection')?.state === 'active';
  const isPPEDetectionActive = aiModels.find(m => m.id === 'ppe_detection')?.state === 'active';

  const handleModelToggle = (modelId: string, enabled: boolean) => {
    onModelToggle(camera.id, modelId, enabled);
  };

  const handleFullscreen = () => {
    onFullscreen(camera.id);
  };

  return (
    <div className="camera-grid-cell">
      {/* Video Area */}
      <div className="camera-grid-cell__video">
        <LiveVideoPlayer
          deviceId={camera.id}
          deviceName={camera.name}
          isAvailable={status === 'live' || status === 'connecting'}
          isDetectionActive={isDetectionActive}
          showOverlays={showOverlays}
          isFallDetectionEnabled={isFallDetectionActive}
          isPPEDetectionEnabled={isPPEDetectionActive}
        />
      </div>

      {/* Status Bar */}
      <div className="camera-grid-cell__status-bar">
        <span className="camera-grid-cell__camera-name" title={camera.name}>
          {camera.name}
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
            models={aiModels}
            onModelToggle={handleModelToggle}
          />
          <span className={`camera-grid-cell__detection ${detectionStatusInfo.className}`}>
            {detectionStatusInfo.icon} {detectionStatusInfo.label}
          </span>
        </div>
        {detectionStatus === 'degraded' && (
          <div className="camera-grid-cell__warning">
            ⚠ AI may be slower or less accurate
          </div>
        )}
      </div>

      {/* Actions Bar */}
      <div className="camera-grid-cell__actions">
        <button
          type="button"
          className="camera-grid-cell__fullscreen-button"
          onClick={handleFullscreen}
          aria-label={`Open ${camera.name} in fullscreen`}
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
    </div>
  );
}