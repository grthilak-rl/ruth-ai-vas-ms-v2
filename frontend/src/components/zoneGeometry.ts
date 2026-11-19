/**
 * Zone geometry shared by the zone editor (GeofenceSetupModal) and the live
 * overlay (LiveVideoPlayer).
 *
 * Store models (any model whose rules need a zone) get zones saved
 * normalised: each point is a fraction (0-1) of the image width and height,
 * marked `coords: 'normalized'`. The store plugin scales them to each frame,
 * so a snapshot drawn at one resolution cannot misplace a zone on frames
 * inferred at another. Zones without the marker are frame pixels (the
 * built-in geo_fencing format).
 */

import type { GeofenceMode, ModelConfig, Point, ZoneConfig } from '../types/geofencing';

/** Six decimals: well under a pixel on any camera. */
const PRECISION = 1e6;

/** Image pixels -> normalised [x, y] pairs. */
export function normalizePoints(points: Point[], width: number, height: number): number[][] {
  return points.map((p) => [
    Math.round((p.x / width) * PRECISION) / PRECISION,
    Math.round((p.y / height) * PRECISION) / PRECISION,
  ]);
}

/** A saved zone's points in image pixels (rounded, as the editor clicks). */
export function zonePointsInImage(zone: ZoneConfig, width: number, height: number): Point[] {
  if (zone.coords === 'normalized') {
    return zone.points.map(([x, y]) => ({ x: Math.round(x * width), y: Math.round(y * height) }));
  }
  return zone.points.map(([x, y]) => ({ x, y }));
}

/**
 * A zone's points on an overlay canvas. Normalised zones scale straight to
 * the canvas; pixel zones are relative to the video's own size.
 */
export function zonePointsOnCanvas(
  zone: ZoneConfig,
  videoWidth: number,
  videoHeight: number,
  canvasWidth: number,
  canvasHeight: number,
): Point[] {
  if (zone.coords === 'normalized') {
    return zone.points.map(([x, y]) => ({ x: x * canvasWidth, y: y * canvasHeight }));
  }
  return zone.points.map(([x, y]) => ({
    x: (x / videoWidth) * canvasWidth,
    y: (y / videoHeight) * canvasHeight,
  }));
}

/**
 * True for the 4 corners the rectangle tool saves: top-left, top-right,
 * bottom-right, bottom-left, axis-aligned. The editor reopens such a zone
 * in rectangle mode, anything else in manual mode.
 */
export function isAxisAlignedRectangle(points: Point[]): boolean {
  if (points.length !== 4) return false;
  const [tl, tr, br, bl] = points;
  return (
    tl.y === tr.y && bl.y === br.y && tl.x === bl.x && tr.x === br.x &&
    tl.x < tr.x && tl.y < bl.y
  );
}

/** Every zone in the configs of the given running models. */
export function zonesForModels(
  modelConfigs: Record<string, ModelConfig>,
  modelIds: string[],
): ZoneConfig[] {
  const zones: ZoneConfig[] = [];
  for (const id of modelIds) {
    for (const zone of modelConfigs[id]?.zones ?? []) {
      if (zone && Array.isArray(zone.points) && zone.points.length >= 3) zones.push(zone);
    }
  }
  return zones;
}

export interface InitialZoneEditorState {
  corners: Point[];
  /** A normalised zone waits for the image size before it can be shown. */
  pendingZone: ZoneConfig | null;
  zoneName: string | null;
  zoneType: string | null;
  capacityLiters: number | null;
  alertThreshold: number | null;
}

/** The saved config, as the editor starts from it. */
export function readInitialConfig(config: ModelConfig | undefined): InitialZoneEditorState {
  const out: InitialZoneEditorState = {
    corners: [], pendingZone: null, zoneName: null, zoneType: null,
    capacityLiters: null, alertThreshold: null,
  };
  if (!config) return out;
  if (config.tank_corners) out.corners = config.tank_corners.map(([x, y]) => ({ x, y }));
  if (config.capacity_liters !== undefined) out.capacityLiters = config.capacity_liters;
  if (config.alert_threshold !== undefined) out.alertThreshold = config.alert_threshold;
  const zone = config.zones?.[0] as ZoneConfig | undefined;
  if (zone) {
    if (zone.points) {
      if (zone.coords === 'normalized') out.pendingZone = zone;
      else out.corners = zone.points.map(([x, y]) => ({ x, y }));
    }
    if (zone.name) out.zoneName = zone.name;
    if (zone.type) out.zoneType = zone.type;
  }
  return out;
}

/** Rectangle mode for nothing yet or an axis-aligned rectangle, else manual. */
export function modeFor(corners: Point[]): GeofenceMode {
  return corners.length === 0 || isAxisAlignedRectangle(corners) ? 'rectangle' : 'manual';
}

/**
 * The zone the editor saves: normalised when `normalizeTo` (the image's
 * natural size) is given, frame pixels when it is omitted. Null when
 * normalising is wanted but the image size is not known yet.
 */
export function buildZone(
  corners: Point[],
  name: string,
  type: string,
  normalizeTo?: { width: number; height: number } | null,
): ZoneConfig | null {
  if (normalizeTo === undefined) {
    return { id: 'zone_1', name, type, points: corners.map((p) => [p.x, p.y]) };
  }
  if (!normalizeTo) return null;
  return {
    id: 'zone_1',
    name,
    type,
    points: normalizePoints(corners, normalizeTo.width, normalizeTo.height),
    coords: 'normalized',
  };
}
