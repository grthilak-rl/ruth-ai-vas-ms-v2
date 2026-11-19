/**
 * GeofenceSetupModal - Modal for setting up geo-fencing/ROI for models
 *
 * Model-aware configuration:
 * - tank_overflow_monitoring: Shows tank capacity and alert threshold
 * - zone models: any model whose rules need a zone (`zoneTypes`, from the
 *   store manifest's `requires_zone`), or the built-in geo_fencing. Shows
 *   zone name and zone type. Store models save the zone normalised (0-1 of
 *   the image size, `coords: 'normalized'`), so snapshot and inference
 *   resolutions cannot disagree; the built-in keeps frame pixels.
 *
 * The saved config is read once per opening (the modal mounts per opening),
 * so a refetch while it is open cannot overwrite the points being edited.
 * A saved zone reopens in rectangle mode if it is an axis-aligned rectangle,
 * otherwise in manual mode; switching mode keeps a complete zone, and only
 * Reset clears it (BL-6).
 */

import { useState, useRef } from 'react';
import { VideoCanvas } from './VideoCanvas';
import type { Point, ModelConfig, GeofenceMode, ZoneConfig } from '../types/geofencing';
import { buildZone, modeFor, readInitialConfig, zonePointsInImage } from './zoneGeometry';
import './GeofenceSetupModal.css';

/** Zone types the built-in geo_fencing model understands. */
const BUILTIN_GEOFENCE_ZONE_TYPES = ['restricted', 'allowed'];

function zoneTypeLabel(type: string): string {
  if (type === 'restricted') return 'Restricted (Alert when entered)';
  if (type === 'allowed') return 'Allowed (Alert when exited)';
  return type.charAt(0).toUpperCase() + type.slice(1).replace(/_/g, ' ');
}

function defaultZoneName(type: string): string {
  if (type === 'restricted') return 'Restricted Zone';
  if (type === 'allowed') return 'Allowed Zone';
  return `${zoneTypeLabel(type)} Zone`;
}


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
  /** Zone types the model's rules need (store models); absent for others. */
  zoneTypes?: string[];
}

export function GeofenceSetupModal({
  isOpen,
  onClose,
  cameraName,
  modelId,
  modelName,
  videoUrl,
  onConfigSaved,
  initialConfig,
  zoneTypes
}: GeofenceSetupModalProps) {
  // Determine model type
  const isTankModel = modelId === 'tank_overflow_monitoring';
  const storeZoneTypes = zoneTypes ?? [];
  const zoneTypeOptions =
    storeZoneTypes.length > 0
      ? storeZoneTypes
      : modelId === 'geo_fencing' ? BUILTIN_GEOFENCE_ZONE_TYPES : [];
  const isZoneModel = zoneTypeOptions.length > 0;
  /** Store models save normalised zones; the built-in reads pixels only. */
  const saveNormalized = storeZoneTypes.length > 0;

  // The saved config, read once for this opening.
  const [initial] = useState(() => readInitialConfig(initialConfig));

  const [mode, setMode] = useState<GeofenceMode>(() => modeFor(initial.corners));
  const [corners, setCorners] = useState<Point[]>(initial.corners);
  const [isDrawing, setIsDrawing] = useState(false);
  const [startPoint, setStartPoint] = useState<Point | null>(null);
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  const pendingZoneRef = useRef<ZoneConfig | null>(initial.pendingZone);

  // Tank-specific configuration (for tank_overflow_monitoring)
  const [capacityLiters, setCapacityLiters] = useState(initial.capacityLiters ?? 1000);
  const [alertThreshold, setAlertThreshold] = useState(initial.alertThreshold ?? 90);

  // Zone configuration (zone models)
  const [zoneType, setZoneType] = useState<string>(() =>
    initial.zoneType && zoneTypeOptions.includes(initial.zoneType)
      ? initial.zoneType
      : (zoneTypeOptions[0] ?? 'restricted'));
  const [zoneName, setZoneName] = useState(() => initial.zoneName ?? defaultZoneName(zoneType));

  // The image's natural size: needed to show a normalised zone, and to save one.
  const handleImageSize = (width: number, height: number) => {
    setImageSize((prev) => (prev && prev.width === width && prev.height === height ? prev : { width, height }));
    const pending = pendingZoneRef.current;
    if (pending) {
      pendingZoneRef.current = null;
      const points = zonePointsInImage(pending, width, height);
      setCorners(points);
      setMode(modeFor(points));
    }
  };

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
    // A complete zone survives a mode switch; only Reset clears it (BL-6).
    // A half-drawn one is cleared: its points belong to the other tool.
    if (corners.length === 4) {
      setStartPoint(null);
      setIsDrawing(false);
    } else {
      handleReset();
    }
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
    } else if (isZoneModel) {
      const zone = buildZone(corners, zoneName, zoneType, saveNormalized ? imageSize : undefined);
      if (!zone) return; // Apply is disabled until the image has loaded
      config = { zones: [zone] };
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
      ...(isZoneModel ? { zone_name: zoneName, zone_type: zoneType } : {})
    });
  };

  const isComplete = corners.length === 4;
  const canApply = isComplete && (!saveNormalized || imageSize !== null);

  const zoneHelp =
    zoneType === 'restricted'
      ? 'Alert will trigger when a person enters this zone'
      : zoneType === 'allowed'
        ? 'Alert will trigger when a person leaves this zone'
        : `Rules of type "${zoneType}" apply inside this zone`;

  const getInstructions = () => {
    const regionType = isZoneModel ? 'zone' : 'tank opening';
    const zoneDone = 'Zone defined. ' + zoneHelp + '.';

    if (mode === 'rectangle') {
      if (corners.length === 0) {
        return `Click and drag to draw a rectangle around the ${regionType}`;
      } else if (isDrawing) {
        return 'Release to complete the rectangle';
      } else {
        if (isZoneModel) {
          return zoneDone;
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
        if (isZoneModel) {
          return zoneDone;
        }
        return 'All 4 corners defined. The system will detect liquid level within this region.';
      }
    }
  };

  const getModalTitle = () => {
    if (isZoneModel) {
      return 'Setup Zone';
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
            onImageSize={handleImageSize}
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

          {/* Zone configuration */}
          {isZoneModel && (
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
                  onChange={(e) => setZoneType(e.target.value)}
                >
                  {zoneTypeOptions.map((type) => (
                    <option key={type} value={type}>{zoneTypeLabel(type)}</option>
                  ))}
                </select>
                <p className="geofence-modal__help">{zoneHelp}</p>
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

          {/* Zone Note */}
          {isZoneModel && isComplete && (zoneType === 'restricted' || zoneType === 'allowed') && (
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
            disabled={!canApply}
          >
            Apply & Close
          </button>
        </div>
      </div>
    </div>
  );
}
