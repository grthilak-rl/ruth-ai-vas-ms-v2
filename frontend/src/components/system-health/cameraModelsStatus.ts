import type {
  CameraModelProblem,
  CameraModelsHealthDetails,
  ComponentHealth,
} from '../../state/api/types';

/**
 * What the "Camera models" health component says, for the System Health
 * card and the top-nav alert. A model can fail on every frame while its
 * camera reads as live (the retired geo_fencing did for 22 minutes), so
 * this is reported on its own rather than folded into a service card.
 */
export interface CameraModelsSummary {
  /** No component (older backend): render nothing. */
  reported: boolean;
  problems: CameraModelProblem[];
  failing: number;
  unavailable: number;
  models: number;
  cameras: number;
  /** The check itself could not run. */
  error: string | null;
}

export function summarizeCameraModels(component: ComponentHealth | undefined): CameraModelsSummary {
  if (!component) {
    return { reported: false, problems: [], failing: 0, unavailable: 0, models: 0, cameras: 0, error: null };
  }
  const details = (component.details ?? {}) as CameraModelsHealthDetails;
  const problems = details.problems ?? [];
  return {
    reported: true,
    problems,
    failing: details.failing ?? problems.filter((p) => p.status === 'failing').length,
    unavailable: details.unavailable ?? problems.filter((p) => p.status === 'unavailable').length,
    models: details.models ?? 0,
    cameras: details.cameras ?? 0,
    error: problems.length === 0 && component.status !== 'healthy' ? component.error ?? 'Check failed' : null,
  };
}

/** "1 camera model not working" / "3 camera models not working". */
export function cameraModelsHeadline(summary: CameraModelsSummary): string {
  const n = summary.problems.length;
  return `${n} camera model${n === 1 ? '' : 's'} not working`;
}

/** One problem as a line: "THILAKCABIN_OUT: geo_fencing — geo_fencing is retired; use geofence". */
export function describeProblem(p: CameraModelProblem): string {
  const state = p.status === 'unavailable' ? 'not installed' : 'not running';
  const where = p.in_session ? '' : ' (saved, not started)';
  return `${p.camera}: ${p.model_id} ${state}${where} — ${p.message ?? ''}`.trim();
}
