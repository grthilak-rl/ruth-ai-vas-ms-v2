import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import {
  type PaneLayout,
  MAX_PANE_COLS,
  MAX_PANE_ROWS,
  fitLayout,
  presetSizeOf,
} from '../../utils/viewingPaneLayout';
import './GridLayoutPicker.css';

interface GridLayoutPickerProps {
  layout: PaneLayout;
  /** Cameras the Fit entry should hold: the monitoring page's selection. */
  fitCount: number;
  onSelect: (layout: PaneLayout) => void;
  /**
   * Aspect of the screen the wall is shown on, for Fit's tie-breaks. Defaults
   * to this window, which is right on the wall itself; a picker hosted
   * elsewhere passes the wall's aspect instead.
   */
  viewportAspect?: number;
  /** 'dark' for the wall toolbar, 'light' for the Camera Monitoring toolbar. */
  variant?: 'dark' | 'light';
  /** Trigger classes, so the button matches the toolbar hosting it. */
  triggerClassName?: string;
  triggerActiveClassName?: string;
}

/**
 * Word-style "insert table" picker: a 5x5 matrix where hovering (or arrowing)
 * highlights rows x columns from the top-left, and clicking (or Enter)
 * applies it. Rows and columns are independent, so 3 x 4 is one click.
 *
 * Roving tabindex: only the focused cell is in the tab order, so Tab moves
 * from the matrix to the Fit entry rather than through 25 cells.
 */
export function GridLayoutPicker({
  layout,
  fitCount,
  onSelect,
  viewportAspect,
  variant = 'dark',
  triggerClassName = 'viewing-pane__toolbar-button',
  triggerActiveClassName = 'viewing-pane__toolbar-button--active',
}: GridLayoutPickerProps) {
  const [open, setOpen] = useState(false);
  // The cell the highlight extends to (inclusive, 1-based rows/cols).
  const [highlight, setHighlight] = useState<PaneLayout>(layout);
  // The keyboard position; the highlight snaps back to it when the pointer leaves.
  const [focusCell, setFocusCell] = useState<PaneLayout>(layout);

  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const cellRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const popoverId = useId();

  const isCustom = presetSizeOf(layout) === null;
  const fit = fitLayout(
    fitCount,
    viewportAspect ?? window.innerWidth / Math.max(window.innerHeight, 1)
  );

  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }, []);

  const openPicker = () => {
    setHighlight(layout);
    setFocusCell(layout);
    setOpen(true);
  };

  // Focus follows the keyboard position while open (including on open).
  useEffect(() => {
    if (!open) return;
    cellRefs.current.get(`${focusCell.rows},${focusCell.cols}`)?.focus();
  }, [open, focusCell]);

  // Click outside closes, without stealing focus back to the trigger.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) close(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open, close]);

  const apply = (next: PaneLayout) => {
    onSelect(next);
    close(true);
  };

  const onPopoverKeyDown = (event: ReactKeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close(true);
    }
  };

  const onGridKeyDown = (event: ReactKeyboardEvent) => {
    const moves: Record<string, [number, number]> = {
      ArrowUp: [-1, 0],
      ArrowDown: [1, 0],
      ArrowLeft: [0, -1],
      ArrowRight: [0, 1],
    };
    const move = moves[event.key];
    if (!move) return; // Enter / Space fall through to the focused cell's click.
    event.preventDefault();
    const next = {
      rows: Math.min(MAX_PANE_ROWS, Math.max(1, focusCell.rows + move[0])),
      cols: Math.min(MAX_PANE_COLS, Math.max(1, focusCell.cols + move[1])),
    };
    setFocusCell(next);
    setHighlight(next);
  };

  return (
    <div
      className={`grid-layout-picker ${variant === 'light' ? 'grid-layout-picker--light' : ''}`}
      ref={rootRef}
    >
      <button
        ref={triggerRef}
        type="button"
        className={`${triggerClassName} ${isCustom ? triggerActiveClassName : ''}`}
        title={isCustom ? `${layout.rows} rows × ${layout.cols} columns` : 'Custom rows × columns'}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? popoverId : undefined}
        onClick={() => (open ? close(false) : openPicker())}
      >
        {isCustom ? `${layout.rows} × ${layout.cols}` : 'Custom'} ▾
      </button>

      {open && (
        <div
          id={popoverId}
          className="grid-layout-picker__popover"
          role="dialog"
          aria-label="Custom grid layout"
          onKeyDown={onPopoverKeyDown}
        >
          <div
            className="grid-layout-picker__matrix"
            role="grid"
            aria-label="Rows by columns"
            onKeyDown={onGridKeyDown}
            onMouseLeave={() => setHighlight(focusCell)}
          >
            {Array.from({ length: MAX_PANE_ROWS }, (_, r) => (
              <div key={r} role="row" className="grid-layout-picker__row">
                {Array.from({ length: MAX_PANE_COLS }, (_, c) => {
                  const rows = r + 1;
                  const cols = c + 1;
                  const lit = rows <= highlight.rows && cols <= highlight.cols;
                  const focused = rows === focusCell.rows && cols === focusCell.cols;
                  const current = rows === layout.rows && cols === layout.cols;
                  return (
                    <div key={c} role="gridcell" aria-selected={current}>
                      <button
                        ref={(el) => {
                          const key = `${rows},${cols}`;
                          if (el) cellRefs.current.set(key, el);
                          else cellRefs.current.delete(key);
                        }}
                        type="button"
                        tabIndex={focused ? 0 : -1}
                        className={`grid-layout-picker__cell ${
                          lit ? 'grid-layout-picker__cell--lit' : ''
                        }`}
                        aria-label={`${rows} × ${cols}`}
                        onMouseEnter={() => setHighlight({ rows, cols })}
                        onFocus={() => {
                          setFocusCell({ rows, cols });
                          setHighlight({ rows, cols });
                        }}
                        onClick={() => apply({ rows, cols })}
                      />
                    </div>
                  );
                })}
              </div>
            ))}
          </div>

          <div className="grid-layout-picker__label" aria-live="polite">
            {highlight.rows} × {highlight.cols}
          </div>

          <button
            type="button"
            className="grid-layout-picker__fit"
            disabled={!fit}
            onClick={() => fit && apply(fit)}
          >
            {fit
              ? `Fit ${fitCount} camera${fitCount === 1 ? '' : 's'} (${fit.rows} × ${fit.cols})`
              : 'Fit (no cameras selected)'}
          </button>
        </div>
      )}
    </div>
  );
}
