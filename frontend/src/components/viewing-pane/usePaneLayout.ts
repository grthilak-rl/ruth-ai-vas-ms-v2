import { useCallback, useEffect, useState } from 'react';
import {
  type PaneLayout,
  getPaneLayout,
  isPaneLayoutStorageKey,
  setPaneLayout,
} from '../../utils/viewingPanePreferences';
import { layoutsEqual } from '../../utils/viewingPaneLayout';

/**
 * The wall's layout, persisted and shared across windows.
 *
 * Camera Monitoring and the wall (normally its own window on the TV) both
 * pick the layout. Writes go to localStorage; the `storage` event — fired in
 * every OTHER same-origin window — lets an already-open wall follow a layout
 * chosen on the monitoring page without a reload, and vice versa.
 */
export function usePaneLayout(): [PaneLayout, (next: PaneLayout) => void] {
  const [layout, setLayoutState] = useState<PaneLayout>(getPaneLayout);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (!isPaneLayoutStorageKey(event.key)) return;
      const next = getPaneLayout();
      setLayoutState((current) => (layoutsEqual(current, next) ? current : next));
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const setLayout = useCallback((next: PaneLayout) => {
    setLayoutState(next);
    setPaneLayout(next);
  }, []);

  return [layout, setLayout];
}
