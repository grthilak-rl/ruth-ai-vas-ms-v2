/**
 * How overlays from several models on one camera are told apart.
 *
 * Applied ONLY when two or more models are drawn on the same frame. With a
 * single model every draw function is called without a style and produces
 * exactly the canvas calls it always has.
 *
 * Colour keeps its meaning across models (red = violation), so models are
 * distinguished by label prefix, line style and label position instead:
 *   - fall: solid person box, label in its usual place, prefixed "FALL · "
 *   - PPE:  dashed person box, label stacked one row ABOVE fall's (its
 *           "Missing: ..." text already sits below the box), prefixed "PPE · "
 */

export interface OverlayStyle {
  /** Prepended to the person label, e.g. "PPE · ". */
  labelPrefix?: string;
  /** Dash pattern for the person box; solid when omitted. */
  lineDash?: number[];
  /** Extra vertical offset (px, negative = up) for the person label. */
  labelOffsetY?: number;
}

/** Height of one person-label row, as drawn by the fall and PPE renderers. */
export const LABEL_ROW_HEIGHT = 22;

export const MULTI_MODEL_STYLES: Readonly<Record<'fall_detection' | 'ppe_detection', OverlayStyle>> = {
  fall_detection: { labelPrefix: 'FALL · ' },
  ppe_detection: { labelPrefix: 'PPE · ', lineDash: [8, 4], labelOffsetY: -LABEL_ROW_HEIGHT },
};

/**
 * Styles for this frame: undefined for every model when fewer than two
 * models are drawn (single-model rendering is unchanged).
 */
export function overlayStylesFor(drawnModelCount: number): {
  fall?: OverlayStyle;
  ppe?: OverlayStyle;
} {
  if (drawnModelCount < 2) return {};
  return { fall: MULTI_MODEL_STYLES.fall_detection, ppe: MULTI_MODEL_STYLES.ppe_detection };
}
