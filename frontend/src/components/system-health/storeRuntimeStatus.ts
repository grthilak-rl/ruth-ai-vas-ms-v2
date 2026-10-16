/**
 * Presentation logic for the "Model store runtime" health card.
 *
 * Kept out of the view so it can be tested directly: these are the rules
 * that decide whether an operator sees the store runtime as broken.
 *
 * The backend reports `degraded` for both "unreachable" and "reachable but
 * some models not ready" — deliberately, so an unreachable store cannot
 * flip overall system health to `unhealthy` and trip alerting meant for
 * database or runtime failures. That makes `details.reachable` the thing
 * the UI has to key on: unreachable renders red, partial renders amber.
 */

import type { ComponentHealth, ModelStoreRuntimeHealthDetails } from '../../state';
import type { ServiceHealthStatus } from './ServiceStatusCard';

function detailsOf(
  component?: ComponentHealth
): ModelStoreRuntimeHealthDetails | undefined {
  return component?.details as ModelStoreRuntimeHealthDetails | undefined;
}

/** True when the store runtime did not answer on the last check. */
export function storeRuntimeIsUnreachable(component?: ComponentHealth): boolean {
  if (!component || component.status === 'disabled') return false;
  return detailsOf(component)?.reachable === false;
}

/**
 * Card status. Unreachable is promoted to `offline` (red) even though the
 * component status is `degraded` — see the module note.
 */
export function deriveStoreRuntimeStatus(
  component?: ComponentHealth
): ServiceHealthStatus {
  if (!component) return 'disabled';
  if (component.status === 'disabled') return 'disabled';
  if (storeRuntimeIsUnreachable(component)) return 'offline';
  if (component.status === 'unhealthy') return 'offline';
  if (component.status === 'degraded') return 'degraded';
  return 'healthy';
}

/** "3 minutes ago" / "2 days ago", for the last-success line. */
export function formatLastSuccess(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 'at an unknown time';
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return 'moments ago';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

export function getModelStoreDescription(
  status: ServiceHealthStatus,
  component: ComponentHealth
): string {
  const details = detailsOf(component);

  if (details?.reachable === false) {
    // Say what broke and how long ago it last worked — the information
    // whose absence let this go unnoticed for twelve days.
    const since = details.last_success_at
      ? ` Last reachable ${formatLastSuccess(details.last_success_at)} (since backend start).`
      : ' Not reachable since this backend started.';
    return `Unreachable: ${component.error ?? 'no response'}.${since} Uploaded models are unavailable.`;
  }

  const ready = details?.models_ready ?? 0;
  const total = details?.models_total ?? 0;

  if (status === 'degraded') {
    const notReady = details?.models_not_ready?.join(', ');
    return `${ready} of ${total} uploaded models ready${notReady ? `. Not loaded: ${notReady}` : ''}.`;
  }
  if (status === 'offline') {
    return 'Model store runtime is not responding. Uploaded models are unavailable.';
  }
  return `${ready} of ${total} uploaded models ready.`;
}
