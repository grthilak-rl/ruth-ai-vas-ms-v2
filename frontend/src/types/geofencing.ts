/**
 * Geo-fencing types for ROI selection
 */

export interface Point {
  x: number;
  y: number;
}

export interface Rectangle {
  topLeft: Point;
  bottomRight: Point;
}

export type GeofenceMode = 'rectangle' | 'manual';

/**
 * Zone configuration for geo_fencing model
 */
export interface ZoneConfig {
  id: string;
  name: string;
  points: number[][];
  /** 'restricted' / 'allowed' for geo-fencing; a store model may name
   *  other zone types in its rules (`requires_zone`). */
  type: string;
  /** 'normalized': points are fractions (0-1) of the image width/height.
   *  Absent: frame pixels (the built-in geo_fencing format). */
  coords?: 'normalized';
}

/**
 * Model configuration - varies by model type
 *
 * tank_overflow_monitoring uses:
 * - tank_corners
 * - capacity_liters
 * - alert_threshold
 *
 * geo_fencing uses:
 * - zones (array of ZoneConfig)
 */
export interface ModelConfig {
  // Tank overflow monitoring fields
  tank_corners?: number[][];
  capacity_liters?: number;
  alert_threshold?: number;

  // Geo-fencing fields
  zones?: ZoneConfig[];

  // Chane tank monitor: optional manual circular ROI (else auto-detect/center)
  roi_circle?: { cx: number; cy: number; r: number };

  // Allow additional fields for future models
  [key: string]: unknown;
}

export interface GeofencingConfig {
  type: 'rectangle' | 'polygon' | 'multi-zone';
  required_fields?: string[];
  supports_circular?: boolean;
}

export interface ModelMetadata {
  model_id: string;
  name: string;
  version: string;
  requires_geofencing?: boolean;
  geofencing_config?: GeofencingConfig;
}
