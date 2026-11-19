/**
 * AI Runtime outage helpers for the System Health view (24 Aug GPU outage).
 */
import type { AIRuntimeHealthDetails } from '../../state';

/**
 * Prominent alert for the two AI failures that stop (or silently slow) all
 * detection: the GPU is missing, or the runtime does not respond.
 */
export function getAIRuntimeAlert(
  component: { status?: string; error?: string | null; details?: unknown } | undefined
): { title: string; detail: string } | null {
  if (!component || component.status !== 'unhealthy') return null;
  const details = (component.details ?? {}) as AIRuntimeHealthDetails;
  if (details.reachable === false) {
    return {
      title: 'AI detection is DOWN - AI Runtime unreachable.',
      detail: component.error ?? 'The AI Runtime is not responding.',
    };
  }
  if (details.gpu_available === false && details.gpu_expected !== false) {
    return {
      title: 'AI detection is DOWN - GPU not available.',
      detail:
        (details.gpu_reason ? `${details.gpu_reason}. ` : '') +
        'Check nvidia-smi on the host (see DEPLOYMENT.md, kernel + NVIDIA driver).',
    };
  }
  return {
    title: 'AI detection is impaired - AI Runtime unhealthy.',
    detail: component.error ?? '',
  };
}
