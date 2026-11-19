import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useHealthQuery, useIsAdmin } from '../../state';
import {
  cameraModelsHeadline,
  describeProblem,
  summarizeCameraModels,
} from '../system-health/cameraModelsStatus';
import './CameraModelsAlert.css';

/**
 * Top-nav system alert: a model on a camera is failing or not installed.
 *
 * A system alert, not a violation: it is never counted with violations or
 * reported as one. Shown only while there is something wrong, from the
 * same /health poll as the status indicator beside it.
 */
export function CameraModelsAlert() {
  const { data } = useHealthQuery();
  const isAdmin = useIsAdmin();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const summary = summarizeCameraModels(data?.components?.camera_models);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  if (summary.problems.length === 0) return null;
  const headline = cameraModelsHeadline(summary);

  return (
    <div className="camera-models-alert" ref={ref}>
      <button
        type="button"
        className="camera-models-alert__button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`${headline}. Click for details.`}
      >
        <span aria-hidden="true">⚠</span> {headline}
      </button>
      {open && (
        <div className="camera-models-alert__panel" role="dialog" aria-label="Camera models not working">
          <ul className="camera-models-alert__list">
            {summary.problems.map((p) => (
              <li key={`${p.device_id}-${p.model_id}-${p.in_session}`}>{describeProblem(p)}</li>
            ))}
          </ul>
          <p className="camera-models-alert__hint">
            Remove or replace the model from the camera&apos;s AI Models picker.
            {isAdmin && (
              <>
                {' '}
                <Link to="/settings/health" onClick={() => setOpen(false)}>
                  System Health
                </Link>
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}
