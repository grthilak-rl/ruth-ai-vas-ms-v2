import type { Device } from '../../state';

/**
 * Drop selected camera ids that are no longer in the list.
 *
 * A camera retired in VAS (disabled, deactivated, deleted) vanishes from
 * every camera list, but its id survived in the saved selection — and
 * still counted toward the grid's capacity. The symptom: 12 cameras
 * listed, 11 ticked, and the footer reading "Selected: 12 / 12" while the
 * twelfth checkbox was greyed out, blocked by a camera nobody could see.
 * 74004 held a slot that way after it was decommissioned.
 *
 * Applied on load and again on save, so a stale id cannot survive a round
 * trip even if it was already persisted.
 *
 * Order is preserved: the selection is the grid's tile order, and
 * re-sorting it would shuffle the operator's wall.
 */
export function pruneSelection(
  selected: readonly string[],
  cameras: readonly Device[]
): string[] {
  // An empty camera list is "not loaded yet", not "every camera is gone".
  // Pruning against it would wipe a valid selection on every refresh.
  if (cameras.length === 0) return [...selected];

  const present = new Set(cameras.map((c) => c.id));
  return selected.filter((id) => present.has(id));
}

/**
 * True when the selection really has filled the grid — as opposed to
 * appearing full because of stale ids.
 */
export function isGridFull(selected: readonly string[], maxCameras: number): boolean {
  return selected.length >= maxCameras;
}
