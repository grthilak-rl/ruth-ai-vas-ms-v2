/**
 * Model ID rules, mirroring ruth-ai-backend/app/services/model_store/ids.py
 * so the edit form can explain a bad ID before saving. The backend still
 * decides (and alone knows which IDs are taken).
 */

export const MODEL_ID_PATTERN = /^[a-z][a-z0-9_]{2,47}$/;
const MODEL_ID_MAX_LENGTH = 48;

export const RESERVED_MODEL_IDS = new Set([
  'fall_detection',
  'ppe_detection',
  'geo_fencing',
  'tank_overflow_monitoring',
  'chane_tank_monitor',
  'chane_tank_overflow',
  'helmet_detection',
  'fire_detection',
  'intrusion_detection',
]);

const RESERVED_PREFIXES = ['test_', 'dummy_', 'broken_'];

/** Why `modelId` breaks the naming standard, or null. */
export function modelIdProblem(modelId: string): string | null {
  if (!MODEL_ID_PATTERN.test(modelId)) {
    return '3–48 characters: a lowercase letter, then lowercase letters, digits or underscores (no capitals, spaces or hyphens)';
  }
  if (RESERVED_MODEL_IDS.has(modelId)) return `"${modelId}" is reserved by a platform model`;
  const prefix = RESERVED_PREFIXES.find((p) => modelId.startsWith(p));
  if (prefix) return `Must not start with ${prefix}`;
  return null;
}

/** The ID the backend would generate from a display name (before uniqueness). */
export function modelIdFromName(displayName: string): string {
  let slug = displayName.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  if (!slug || !/^[a-z]/.test(slug)) slug = `model_${slug}`.replace(/_+$/, '');
  if (RESERVED_PREFIXES.some((p) => slug.startsWith(p))) slug = `model_${slug}`;
  if (slug.length < 3) slug = `${slug}_model`;
  return slug.slice(0, MODEL_ID_MAX_LENGTH - 4).replace(/_+$/, '');
}
