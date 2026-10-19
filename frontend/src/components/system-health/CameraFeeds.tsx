import { describeFeedProblem, feedSummary } from '../../state/api/cameraFeeds';
import type { Device } from '../../state';
import './MonitoringCoverage.css';

/**
 * "Camera feeds: 11 of 12 healthy" — is video arriving and being recorded?
 *
 * Measured by VAS from frames and recording segments, not from whether a
 * stream is configured as running. Sits above Monitoring coverage because
 * it is the more basic question: a camera with no video can't be monitored.
 * Shares the coverage section's styling so the two read as one block.
 */
export function CameraFeeds({
  devices,
  isLoading = false,
}: {
  devices: Device[];
  isLoading?: boolean;
}) {
  if (isLoading) {
    return (
      <section className="coverage coverage--loading">
        <span className="coverage__label">Camera feeds</span>
        <span className="coverage__muted">Checking…</span>
      </section>
    );
  }

  const summary = feedSummary(devices);
  const tone = summary.expected === 0 ? 'none' : summary.problems.length > 0 ? 'warn' : 'ok';

  return (
    <section className={`coverage coverage--${tone}`} aria-live="polite">
      <div className="coverage__headline">
        <span className="coverage__label">Camera feeds</span>
        <span className="coverage__ratio">
          {summary.expected === 0 ? (
            'No cameras reporting'
          ) : (
            <>
              <strong>
                {summary.healthy} of {summary.expected}
              </strong>{' '}
              healthy
            </>
          )}
        </span>
      </div>

      {summary.problems.length > 0 && (
        <div className="coverage__detail" role="alert">
          <ul className="coverage__list">
            {summary.problems.map(({ device }) => (
              <li key={device.id}>
                <span className="coverage__camera">{device.display_name || device.name}</span>
                <span className="coverage__since"> — {describeFeedProblem(device)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {summary.unknown > 0 && (
        <p className="coverage__muted">
          {summary.unknown} camera{summary.unknown === 1 ? '' : 's'} not yet reported by VAS.
        </p>
      )}
    </section>
  );
}
