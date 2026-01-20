/**
 * GeofenceSetupModal - Modal for setting up geo-fencing/ROI for models
 *
 * Model-aware configuration:
 * - tank_overflow_monitoring: Shows tank capacity and alert threshold
 * - geo_fencing: Shows zone name and zone type (restricted/allowed)
 */

import { useState, useEffect } from 'react';
import { VideoCanvas } from './VideoCanvas';
import type { Point, ModelConfig, GeofenceMode, ZoneConfig } from '../types/geofencing';
import './GeofenceSetupModal.css';

interface GeofenceSetupModalProps {
  isOpen: boolean;
  onClose: () => void;
  cameraId: string;
  cameraName: string;
  modelId: string;
  modelName: string;
  videoUrl: string;
  onConfigSaved: (config: ModelConfig) => void;
  initialConfig?: ModelConfig;
}

export function GeofenceSetupModal({
  isOpen,
  onClose,
  cameraName,
  modelId,
  modelName,
  videoUrl,
  onConfigSaved,
  initialConfig
}: GeofenceSetupModalProps) {
  const [mode, setMode] = useState<GeofenceMode>('rectangle');
  const [corners, setCorners] = useState<Point[]>([]);
  const [isDrawing, setIsDrawing] = useState(false);
  const [startPoint, setStartPoint] = useState<Point | null>(null);

  // Tank-specific configuration (for tank_overflow_monitoring)
  const [capacityLiters, setCapacityLiters] = useState(1000);
  const [alertThreshold, setAlertThreshold] = useState(90);

  // Geo-fencing specific configuration (for geo_fencing)
  const [zoneName, setZoneName] = useState('Restricted Zone');
  const [zoneType, setZoneType] = useState<'restricted' | 'allowed'>('restricted');

  // Determine model type
  const isTankModel = modelId === 'tank_overflow_monitoring';
  const isGeoFencingModel = modelId === 'geo_fencing';

  // Initialize from existing config
  useEffect(() => {
    if (initialConfig) {
      // Tank model config
      if (initialConfig.tank_corners) {
        setCorners(initialConfig.tank_corners.map(([x, y]) => ({ x, y })));
      }
      if (initialConfig.capacity_liters !== undefined) {
        setCapacityLiters(initialConfig.capacity_liters);
      }
      if (initialConfig.alert_threshold !== undefined) {
        setAlertThreshold(initialConfig.alert_threshold);
      }

      // Geo-fencing model config
      if (initialConfig.zones && initialConfig.zones.length > 0) {
        const zone = initialConfig.zones[0] as ZoneConfig;
        if (zone.points) {
          setCorners(zone.points.map(([x, y]) => ({ x, y })));
        }
        if (zone.name) {
          setZoneName(zone.name);
        }
        if (zone.type) {
          setZoneType(zone.type);
        }
      }
    }
  }, [initialConfig]);

  // Rectangle mode handlers
  const handleMouseDown = (point: Point) => {
    if (mode === 'rectangle') {
      setStartPoint(point);
      setCorners([point]);
      setIsDrawing(true);
    }
  };

  const handleMouseMove = (point: Point) => {
    if (isDrawing && mode === 'rectangle' && startPoint) {
      // Update the second corner while dragging
      setCorners([startPoint, point]);
    }
  };

  const handleMouseUp = (point: Point) => {
    if (isDrawing && mode === 'rectangle' && startPoint) {
      // Convert rectangle to 4 corners: top-left, top-right, bottom-right, bottom-left
      const x1 = Math.min(startPoint.x, point.x);
      const y1 = Math.min(startPoint.y, point.y);
      const x2 = Math.max(startPoint.x, point.x);
      const y2 = Math.max(startPoint.y, point.y);

      setCorners([
        { x: x1, y: y1 },  // top-left
        { x: x2, y: y1 },  // top-right
        { x: x2, y: y2 },  // bottom-right
        { x: x1, y: y2 }   // bottom-left
      ]);

      setIsDrawing(false);
    }
  };

  // Manual mode handlers
  const handleClick = (point: Point) => {
    // In rectangle mode, clicks should not do anything
    // (rectangle is drawn via drag, not clicks)
    if (mode === 'rectangle') {
      return;
    }

    if (mode === 'manual' && corners.length < 4) {
      setCorners([...corners, point]);
    }
  };

  const handleReset = () => {
    setCorners([]);
    setStartPoint(null);
    setIsDrawing(false);
  };

  const handleModeChange = (newMode: GeofenceMode) => {
    setMode(newMode);
    handleReset();
  };

  const handleApply = () => {
    if (corners.length !== 4) {
      return;
    }

    const cornerArray = corners.map(p => [p.x, p.y]);

    let config: ModelConfig;

    if (isTankModel) {
      // Tank overflow monitoring config
      config = {
        tank_corners: cornerArray,
        capacity_liters: capacityLiters,
        alert_threshold: alertThreshold
      };
    } else if (isGeoFencingModel) {
      // Geo-fencing config
      config = {
        zones: [
          {
            id: 'zone_1',
            name: zoneName,
            points: cornerArray,
            type: zoneType
          }
        ]
      };
    } else {
      // Generic fallback
      config = {
        tank_corners: cornerArray
      };
    }

    onConfigSaved(config);
  };

  const handleTestDetection = () => {
    // TODO: Implement test detection
    const cornerArray = corners.map(p => [p.x, p.y]);
    console.log('Test detection with config:', {
      modelId,
      corners: cornerArray,
      ...(isTankModel ? { capacity_liters: capacityLiters, alert_threshold: alertThreshold } : {}),
      ...(isGeoFencingModel ? { zone_name: zoneName, zone_type: zoneType } : {})
    });
  };

  const isComplete = corners.length === 4;

  const getInstructions = () => {
    const regionType = isGeoFencingModel ? 'restricted zone' : 'tank opening';

    if (mode === 'rectangle') {
      if (corners.length === 0) {
        return `Click and drag to draw a rectangle around the ${regionType}`;
      } else if (isDrawing) {
        return 'Release to complete the rectangle';
      } else {
        if (isGeoFencingModel) {
          return 'Zone defined. The system will alert when persons enter this area.';
        }
        return 'Rectangle defined. The system will detect liquid level within this region.';
      }
    } else {
      const remaining = 4 - corners.length;
      if (remaining === 4) {
        return `Click the top-left corner of the ${regionType}`;
      } else if (remaining === 3) {
        return `Click the top-right corner of the ${regionType}`;
      } else if (remaining === 2) {
        return `Click the bottom-right corner of the ${regionType}`;
      } else if (remaining === 1) {
        return `Click the bottom-left corner of the ${regionType}`;
      } else {
        if (isGeoFencingModel) {
          return 'Zone defined. The system will alert when persons enter this area.';
        }
        return 'All 4 corners defined. The system will detect liquid level within this region.';
      }
    }
  };

  const getModalTitle = () => {
    if (isGeoFencingModel) {
      return 'Setup Restricted Zone';
    }
    return 'Setup Geo-Fence';
  };

  if (!isOpen) return null;

  return (
    <div className="geofence-modal-overlay">
      <div className="geofence-modal">
        <div className="geofence-modal__header">
          <div className="geofence-modal__title">
            <span>{getModalTitle()}</span>
            <span className="geofence-modal__badge">{modelName}</span>
            <span className="geofence-modal__camera">{cameraName}</span>
          </div>
          <button
            type="button"
            className="geofence-modal__close"
            onClick={onClose}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="geofence-modal__body">
          {/* Video Canvas */}
          <VideoCanvas
            videoUrl={videoUrl}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onClick={handleClick}
            corners={corners}
            isDrawing={isDrawing}
            mode={mode}
          />

          {/* Mode Selection */}
          <div className="geofence-modal__section">
            <label className="geofence-modal__label">Selection Mode</label>
            <div className="geofence-modal__radio-group">
              <label className="geofence-modal__radio">
                <input
                  type="radio"
                  name="mode"
                  value="rectangle"
                  checked={mode === 'rectangle'}
                  onChange={() => handleModeChange('rectangle')}
                />
                <span>Rectangle Mode <span className="geofence-modal__recommended">(Recommended)</span></span>
              </label>
              <label className="geofence-modal__radio">
                <input
                  type="radio"
                  name="mode"
                  value="manual"
                  checked={mode === 'manual'}
                  onChange={() => handleModeChange('manual')}
                />
                <span>Manual (4 corners)</span>
              </label>
            </div>
          </div>

          {/* Instructions */}
          <div className={`geofence-modal__alert ${isComplete ? 'geofence-modal__alert--success' : 'geofence-modal__alert--info'}`}>
            <strong>{isComplete ? 'Region Defined!' : 'Instructions'}</strong>
            <p>{getInstructions()}</p>
          </div>

          {/* Tank-specific Configuration */}
          {isTankModel && (
            <div className="geofence-modal__config-row">
              <div className="geofence-modal__field">
                <label className="geofence-modal__label">Tank Capacity (liters)</label>
                <input
                  type="number"
                  className="geofence-modal__input"
                  value={capacityLiters}
                  onChange={(e) => setCapacityLiters(Number(e.target.value))}
                  min={1}
                  max={1000000}
                />
              </div>

              <div className="geofence-modal__field">
                <label className="geofence-modal__label">
                  Alert Threshold: {alertThreshold}%
                </label>
                <input
                  type="range"
                  className="geofence-modal__slider"
                  value={alertThreshold}
                  onChange={(e) => setAlertThreshold(Number(e.target.value))}
                  min={50}
                  max={100}
                  step={5}
                />
                <p className="geofence-modal__help">
                  Alert when tank reaches {alertThreshold}% capacity
                </p>
              </div>
            </div>
          )}

          {/* Geo-fencing specific Configuration */}
          {isGeoFencingModel && (
            <div className="geofence-modal__config-row">
              <div className="geofence-modal__field">
                <label className="geofence-modal__label">Zone Name</label>
                <input
                  type="text"
                  className="geofence-modal__input"
                  value={zoneName}
                  onChange={(e) => setZoneName(e.target.value)}
                  placeholder="Enter zone name"
                  maxLength={50}
                />
              </div>

              <div className="geofence-modal__field">
                <label className="geofence-modal__label">Zone Type</label>
                <select
                  className="geofence-modal__select"
                  value={zoneType}
                  onChange={(e) => setZoneType(e.target.value as 'restricted' | 'allowed')}
                >
                  <option value="restricted">Restricted (Alert when entered)</option>
                  <option value="allowed">Allowed (Alert when exited)</option>
                </select>
                <p className="geofence-modal__help">
                  {zoneType === 'restricted'
                    ? 'Alert will trigger when a person enters this zone'
                    : 'Alert will trigger when a person leaves this zone'}
                </p>
              </div>
            </div>
          )}

          {/* Tank Shape Support Note (Tank model only) */}
          {isTankModel && isComplete && (
            <div className="geofence-modal__note">
              <strong>Note:</strong> This configuration works for both rectangular and circular tank openings.
              The AI will automatically detect the liquid surface within the selected region.
            </div>
          )}

          {/* Geo-fencing Note */}
          {isGeoFencingModel && isComplete && (
            <div className="geofence-modal__note">
              <strong>Note:</strong> The system uses person detection to monitor this zone.
              {zoneType === 'restricted'
                ? ' Alerts will be generated when any person is detected inside the defined area.'
                : ' Alerts will be generated when a person leaves the defined area.'}
            </div>
          )}
        </div>

        <div className="geofence-modal__footer">
          <button
            type="button"
            className="geofence-modal__button geofence-modal__button--secondary"
            onClick={handleReset}
            disabled={corners.length === 0}
          >
            Reset
          </button>
          <button
            type="button"
            className="geofence-modal__button geofence-modal__button--outline"
            onClick={handleTestDetection}
            disabled={!isComplete}
          >
            Test Detection
          </button>
          <button
            type="button"
            className="geofence-modal__button geofence-modal__button--secondary"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="button"
            className="geofence-modal__button geofence-modal__button--primary"
            onClick={handleApply}
            disabled={!isComplete}
          >
            Apply & Close
          </button>
        </div>
      </div>
    </div>
  );
}
