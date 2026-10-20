import { describe, expect, it } from 'vitest';
import { pruneSelection, isGridFull } from '../pruneSelection';
import type { Device } from '../../../state';

/**
 * The reported bug: 12 cameras listed, 11 ticked, footer reading
 * "Selected: 12 / 12", and the twelfth checkbox greyed out. A camera
 * retired in VAS (74004) had vanished from the list but survived in the
 * saved selection, where it still occupied a grid slot — invisible, and
 * blocking a camera the operator could see.
 */

function cam(id: string): Device {
  return { id, name: id, is_active: true, enabled: true, streaming: {} } as Device;
}

const LISTED = ['75080', '75081', '75129'].map(cam);

describe('pruneSelection', () => {
  it('drops an id that is no longer listed', () => {
    // 74004 decommissioned: gone from the list, still in the selection.
    expect(pruneSelection(['75080', '74004', '75081'], LISTED)).toEqual(['75080', '75081']);
  });

  it('frees the slot the stale id was holding', () => {
    const saved = ['75080', '75081', '74004'];
    expect(isGridFull(saved, 3)).toBe(true);           // the symptom
    expect(isGridFull(pruneSelection(saved, LISTED), 3)).toBe(false);  // the fix
  });

  it('keeps the order, because it is the grid tile order', () => {
    expect(pruneSelection(['75129', '74004', '75080'], LISTED)).toEqual(['75129', '75080']);
  });

  it('leaves a clean selection untouched', () => {
    expect(pruneSelection(['75080', '75081'], LISTED)).toEqual(['75080', '75081']);
  });

  it('does not wipe the selection while the camera list is still loading', () => {
    // An empty list means "not loaded yet", not "every camera is gone".
    // Pruning against it would clear the operator's wall on every refresh.
    expect(pruneSelection(['75080', '75081'], [])).toEqual(['75080', '75081']);
  });

  it('handles an empty selection', () => {
    expect(pruneSelection([], LISTED)).toEqual([]);
  });

  it('drops every id when none are listed any more', () => {
    expect(pruneSelection(['74004', 'gone'], LISTED)).toEqual([]);
  });
});

describe('isGridFull', () => {
  it('is true only at or above the limit', () => {
    expect(isGridFull(['a', 'b'], 3)).toBe(false);
    expect(isGridFull(['a', 'b', 'c'], 3)).toBe(true);
    // Defensive: an over-full selection from an older, larger layout.
    expect(isGridFull(['a', 'b', 'c', 'd'], 3)).toBe(true);
  });
});
