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
  type: 'restricted' | 'allowed';
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

  // Allow additional fields for future models
  [key: string]: any;
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
