import { useState, useEffect, useCallback } from 'react';
import { LiveVideoPlayer } from '../components/video/LiveVideoPlayer';
import type { AIModel } from '../components/cameras/AIModelSelector';
import type { Device } from '../state';
import './CameraFullscreenPage.css';

/**
 * CameraFullscreenPage Component
 *
 * Fullscreen camera view that opens in a new browser tab.
 * Per F7 §7:
 * - Single camera view with all controls
 * - Tab title: "{Camera Name} - Ruth AI Live"
 * - Full viewport video with detection overlays
 * - Camera info, AI detection controls, and today's violations
 * - Close button closes the tab
 *
 * Behavior per F7 §7.1:
 * - Opened via fullscreen button from grid cell
 * - Opens in new tab at /cameras/fullscreen/:id
 * - Original dashboard remains open when this tab is closed
 */

interface CameraFullscreenPageProps {
  device: Device | undefined;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}

export function CameraFullscreenPage({
  device,
  isLoading,
  isError,
  onRetry,
}: CameraFullscreenPageProps) {
  // AI model toggles (session-scoped)
  const [aiModelToggles, setAiModelToggles] = useState<Record<string, boolean>>({
    fall_detection: true, // Default to enabled
  });

  // Update document title
  useEffect(() => {
    if (device) {
      document.title = `${device.name} - Ruth AI Live`;
    }
    return () => {
      document.title = 'Ruth AI'; // Reset on unmount
    };
  }, [device]);

  // Handle AI model toggle
  const handleModelToggle = useCallback((modelId: string, enabled: boolean) => {
    setAiModelToggles((prev) => ({
      ...prev,
      [modelId]: enabled,
    }));
  }, []);

  // Handle close
  const handleClose = useCallback(() => {
    window.close();
  }, []);

  // Get AI models for camera (mock for now)
  const aiModels: AIModel[] = [
    {
      id: 'fall_detection',
      name: 'Fall Detection',
      state: aiModelToggles['fall_detection'] ? 'active' : 'inactive',
    },
  ];

  const isDetectionActive = aiModels.some((m) => m.state === 'active');
  const showOverlays = isDetectionActive;
  const cameraStatus = device?.is_active ? 'live' : 'offline';

  // Loading state
  if (isLoading) {
    return (
      <div className="camera-fullscreen-page">
        <div className="camera-fullscreen-page__header">
          <div className="camera-fullscreen-page__brand">
            <span className="camera-fullscreen-page__logo">●</span> Ruth AI
          </div>
          <div className="camera-fullscreen-page__loading">Loading...</div>
          <button
            type="button"
            className="camera-fullscreen-page__close"
            onClick={handleClose}
            aria-label="Close"
          >
            Close ✕
          </button>
        </div>
        <div className="camera-fullscreen-page__video-container">
          <div className="camera-fullscreen-page__skeleton" />
        </div>
      </div>
    );
  }

  // Error state
  if (isError || !device) {
    return (
      <div className="camera-fullscreen-page">
        <div className="camera-fullscreen-page__header">
          <div className="camera-fullscreen-page__brand">
            <span className="camera-fullscreen-page__logo">●</span> Ruth AI
          </div>
          <div className="camera-fullscreen-page__error">⚠ Error</div>
          <button
            type="button"
            className="camera-fullscreen-page__close"
            onClick={handleClose}
            aria-label="Close"
          >
            Close ✕
          </button>
        </div>
        <div className="camera-fullscreen-page__error-state">
          <div className="camera-fullscreen-page__error-content">
            <p className="camera-fullscreen-page__error-title">Camera not found</p>
            <p className="camera-fullscreen-page__error-message">
              This camera is no longer available.
            </p>
            <button
              type="button"
              className="camera-fullscreen-page__retry-button"
              onClick={onRetry}
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Main state
  return (
    <div className="camera-fullscreen-page">
      {/* Header */}
      <div className="camera-fullscreen-page__header">
        <div className="camera-fullscreen-page__brand">
          <span className="camera-fullscreen-page__logo">●</span> Ruth AI — {device.name}
        </div>
        <div className="camera-fullscreen-page__system-status">
          <span className="camera-fullscreen-page__system-status-icon">●</span> All Systems OK
        </div>
        <button
          type="button"
          className="camera-fullscreen-page__close"
          onClick={handleClose}
          aria-label="Close"
        >
          Close ✕
        </button>
      </div>

      {/* Video Container */}
      <div className="camera-fullscreen-page__video-container">
        <LiveVideoPlayer
          deviceId={device.id}
          deviceName={device.name}
          isAvailable={cameraStatus === 'live'}
          isDetectionActive={isDetectionActive}
          showOverlays={showOverlays}
        />
      </div>

      {/* Info Panel */}
      <div className="camera-fullscreen-page__info-panel">
        {/* Camera Info */}
        <div className="camera-fullscreen-page__info-section">
          <h3 className="camera-fullscreen-page__info-title">CAMERA INFO</h3>
          <div className="camera-fullscreen-page__info-content">
            <div className="camera-fullscreen-page__info-item">
              <span className="camera-fullscreen-page__info-label">Status:</span>
              <span
                className={`camera-fullscreen-page__info-value camera-fullscreen-page__info-value--${cameraStatus}`}
              >
                {cameraStatus === 'live' ? '● Live' : '○ Offline'}
              </span>
            </div>
            <div className="camera-fullscreen-page__info-item">
              <span className="camera-fullscreen-page__info-label">Stream:</span>
              <span className="camera-fullscreen-page__info-value">
                {cameraStatus === 'live' ? 'Active' : 'Inactive'}
              </span>
            </div>
          </div>
        </div>

        {/* AI Detection */}
        <div className="camera-fullscreen-page__info-section">
          <h3 className="camera-fullscreen-page__info-title">AI DETECTION</h3>
          <div className="camera-fullscreen-page__info-content">
            <div className="camera-fullscreen-page__ai-models">
              {aiModels.map((model) => (
                <label key={model.id} className="camera-fullscreen-page__ai-model-item">
                  <input
                    type="checkbox"
                    checked={model.state === 'active'}
                    onChange={(e) => handleModelToggle(model.id, e.target.checked)}
                    className="camera-fullscreen-page__ai-model-checkbox"
                  />
                  <span className="camera-fullscreen-page__ai-model-name">{model.name}</span>
                  <span
                    className={`camera-fullscreen-page__ai-model-status camera-fullscreen-page__ai-model-status--${model.state}`}
                  >
                    {model.state === 'active' ? '● Active' : '○ Inactive'}
                  </span>
                </label>
              ))}
            </div>
          </div>
        </div>

        {/* Today's Violations */}
        <div className="camera-fullscreen-page__info-section">
          <div className="camera-fullscreen-page__violations-header">
            <h3 className="camera-fullscreen-page__info-title">TODAY'S VIOLATIONS (0)</h3>
            <a href="/alerts" className="camera-fullscreen-page__view-all" target="_blank">
              View All →
            </a>
          </div>
          <div className="camera-fullscreen-page__info-content">
            <p className="camera-fullscreen-page__no-violations">No violations detected today</p>
          </div>
        </div>
      </div>
    </div>
  );
}