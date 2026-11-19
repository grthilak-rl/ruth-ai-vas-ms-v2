import type { ComponentHealth } from '../../state/api/types';
import { describeProblem, summarizeCameraModels } from './cameraModelsStatus';
import './CameraModelsCard.css';

/**
 * Camera models: is every model on every camera actually working?
 *
 * Failing (no result for 60 s) and unavailable (not installed, including
 * saved models a resume left out) are listed by camera. A model failing on
 * every frame used to be visible only in the backend log.
 */
export function CameraModelsCard({ component }: { component: ComponentHealth | undefined }) {
  const summary = summarizeCameraModels(component);
  if (!summary.reported) return null;
  const hasProblems = summary.problems.length > 0 || summary.error !== null;

  return (
    <section
      className={`camera-models camera-models--${hasProblems ? 'warn' : 'ok'}`}
      aria-live="polite"
      data-testid="camera-models-card"
    >
      <div className="camera-models__headline">
        <span className="camera-models__label">Camera models</span>
        <span className="camera-models__summary">
          {summary.problems.length === 0
            ? `all ${summary.models} running on ${summary.cameras} camera${summary.cameras === 1 ? '' : 's'}`
            : [
                summary.failing > 0 && `${summary.failing} failing`,
                summary.unavailable > 0 && `${summary.unavailable} not installed`,
              ]
                .filter(Boolean)
                .join(', ')}
        </span>
      </div>

      {summary.error && (
        <p className="camera-models__error" role="alert">
          {summary.error}
        </p>
      )}

      {summary.problems.length > 0 && (
        <ul className="camera-models__list" role="alert">
          {summary.problems.map((p) => (
            <li key={`${p.device_id}-${p.model_id}-${p.in_session}`}>{describeProblem(p)}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
