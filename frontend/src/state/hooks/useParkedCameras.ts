import { useEffect, useState } from 'react';
import { apiGet } from '../api/client';

/**
 * Device ids the auto-resume reconciler has given up on for now.
 *
 * BL-11 A. A parked camera has live video and working dependencies and
 * still will not start inference — a real fault that nothing will clear
 * on its own, so it earns a badge on the tile rather than only a line on
 * System Health, which an operator watching the wall may never open.
 *
 * Fetched once for the whole grid: a per-cell fetch would be one request
 * per camera every refresh for a list that is almost always empty.
 */

const REFRESH_MS = 30000;

interface ParkedResponse {
  parked?: { device_id: string }[];
}

export function useParkedCameras(): Set<string> {
  const [parked, setParked] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      apiGet<ParkedResponse>('/api/v1/health/auto-resume')
        .then((r) => {
          if (cancelled) return;
          const res = r as ParkedResponse;
          setParked(new Set((res.parked ?? []).map((p) => p.device_id)));
        })
        // A failed check must not blank existing badges or throw: not
        // knowing is not the same as "no camera is parked".
        .catch(() => undefined);
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  return parked;
}
