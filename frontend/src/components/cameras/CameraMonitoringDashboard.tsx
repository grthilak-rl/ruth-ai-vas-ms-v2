import { useState, useEffect, useMemo, useCallback } from 'react';
import { CameraGridSelector } from './CameraGridSelector';
import { CameraSelectorDropdown } from './CameraSelectorDropdown';
import { CameraGridCell } from './CameraGridCell';
import type { AIModel } from './AIModelSelector';
import type { Device } from '../../state';
import {
  type GridSize,
  getGridSize,
  setGridSize,
  getSelectedCameraIds,
  setSelectedCameraIds,
  autoSelectCameras,
  getMaxCameras,
} from '../../utils/cameraGridPreferences';
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
 * - AI model toggles are session-scoped (reset on page reload)
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

export function CameraMonitoringDashboard({
  cameras,
  isLoading,
  isError,
  onRetry,
}: CameraMonitoringDashboardProps) {
  // Grid size state
  const [gridSize, setGridSizeState] = useState<GridSize>(getGridSize());

  // Selected cameras state
  const [selectedCameraIds, setSelectedCameraIdsState] = useState<string[]>(() =>
    getSelectedCameraIds()
  );

  // AI model toggles (session-scoped, per F7)
  // Map of cameraId -> modelId -> enabled
  const [aiModelToggles, setAiModelToggles] = useState<Record<string, Record<string, boolean>>>({});

  // Auto-select cameras when cameras list or grid size changes
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

  // Handle AI model toggle
  const handleModelToggle = useCallback((cameraId: string, modelId: string, enabled: boolean) => {
    setAiModelToggles((prev) => ({
      ...prev,
      [cameraId]: {
        ...(prev[cameraId] || {}),
        [modelId]: enabled,
      },
    }));
  }, []);

  // Handle fullscreen
  const handleFullscreen = useCallback(
    (cameraId: string) => {
      window.open(`/cameras/fullscreen/${cameraId}`, '_blank');
    },
    []
  );

  // Get selected cameras
  const selectedCameras = useMemo(() => {
    return cameras.filter((camera) => selectedCameraIds.includes(camera.id));
  }, [cameras, selectedCameraIds]);

  // Get AI models for a camera (mock for now, will be replaced with actual API data)
  const getAIModelsForCamera = useCallback(
    (cameraId: string): AIModel[] => {
      // Mock AI models - in real implementation, this would come from API
      // Default to inactive (false) - user must explicitly enable AI detection
      const isFallDetectionEnabled = aiModelToggles[cameraId]?.['fall_detection'] === true;

      const fallDetectionModel: AIModel = {
        id: 'fall_detection',
        name: 'Fall Detection',
        state: isFallDetectionEnabled ? 'active' : 'inactive',
      };

      return [fallDetectionModel];
    },
    [aiModelToggles]
  );

  // Get detection status for a camera
  const getDetectionStatusForCamera = useCallback(
    (cameraId: string): 'active' | 'degraded' | 'unavailable' | 'plain' => {
      const models = getAIModelsForCamera(cameraId);
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
      </div>

      <div
        className={`camera-monitoring-dashboard__grid camera-monitoring-dashboard__grid--${gridSize}x${gridSize}`}
      >
        {gridCells.map((cell, index) =>
          cell.type === 'camera' ? (
            <CameraGridCell
              key={cell.camera.id}
              camera={cell.camera}
              status={getCameraStatus(cell.camera)}
              detectionStatus={getDetectionStatusForCamera(cell.camera.id)}
              aiModels={getAIModelsForCamera(cell.camera.id)}
              violationCount={0} // TODO: Wire up actual violation count
              onModelToggle={handleModelToggle}
              onFullscreen={handleFullscreen}
            />
          ) : (
            <div key={`empty-${index}`} className="camera-monitoring-dashboard__empty-cell">
              <div className="camera-monitoring-dashboard__empty-cell-icon">+</div>
              <p className="camera-monitoring-dashboard__empty-cell-text">Add Camera</p>
              <p className="camera-monitoring-dashboard__empty-cell-subtext">
                Click to select from available cameras
              </p>
            </div>
          )
        )}
      </div>
    </div>
  );
}