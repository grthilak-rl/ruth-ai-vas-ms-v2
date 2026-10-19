import {
  coverageSummary,
  formatAbsentFor,
  type CoverageSummary,
} from '../../state/api/coverage';
import type { Device } from '../../state';
import { describeFeedProblem } from '../../state/api/cameraFeeds';
import './MonitoringCoverage.css';

/**
 * "Monitoring coverage: 11 of 12 cameras" — BL-11.
 *
 * System Health reported on services (database, Redis, runtimes) but never
 * on the question an operator actually needs answered: *are the cameras
 * being watched?* Camera 74004 ran 21.3 hours with live video and no
 * inference while every service on this page was green.
 *
 * Placed above the service cards deliberately. A degraded Redis is worth
 * knowing; a camera nobody is watching is worth knowing first.
 */

function tone(summary: CoverageSummary): 'ok' | 'warn' | 'none' {
  if (summary.expected === 0) return 'none';
  return summary.uncovered.length > 0 ? 'warn' : 'ok';
}

export function MonitoringCoverage({
  devices,
  isLoading = false,
}: {
  devices: Device[];
  isLoading?: boolean;
}) {
  if (isLoading) {
    return (
      <section className="coverage coverage--loading">
        <span className="coverage__label">Monitoring coverage</span>
        <span className="coverage__muted">Checking…</span>
      </section>
    );
  }

  const summary = coverageSummary(devices);
  const state = tone(summary);

  return (
    <section className={`coverage coverage--${state}`} aria-live="polite">
      <div className="coverage__headline">
        <span className="coverage__label">Monitoring coverage</span>
        <span className="coverage__ratio">
          {summary.expected === 0 ? (
            'No cameras streaming'
          ) : (
            <>
              <strong>
                {summary.covered} of {summary.expected}
              </strong>{' '}
              {summary.expected === 1 ? 'camera' : 'cameras'}
            </>
          )}
        </span>
      </div>

      {summary.uncovered.length > 0 && (
        <div className="coverage__detail" role="alert">
          <p className="coverage__alert">
            {summary.uncovered.length === 1
              ? 'This camera is streaming video but nothing is analysing it:'
              : `${summary.uncovered.length} cameras are streaming video but nothing is analysing them:`}
          </p>
          <ul className="coverage__list">
            {summary.uncovered.map(({ device, absentForMs }) => (
              <li key={device.id}>
                <span className="coverage__camera">
                  {device.display_name || device.name}
                </span>
                <span className="coverage__since">
                  {' — no detection for '}
                  {formatAbsentFor(absentForMs)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Settling cameras are shown but not alarming: this is what a
          deploy or a model change looks like for a few seconds, and
          hiding it entirely would make the ratio appear to flicker for
          no visible reason. */}
      {summary.uncovered.length === 0 && summary.settling.length > 0 && (
        <p className="coverage__muted">
          {summary.settling.length} starting up…
        </p>
      )}

      {/* Named, not just counted: "1 camera not streaming" hid which one
          and for how long. Not counted in the ratio — no video is a feed
          problem (Camera feeds, above), not a coverage gap. */}
      {summary.noVideo > 0 && (
        <div className="coverage__muted">
          <p>
            {summary.noVideo} camera{summary.noVideo === 1 ? ' has' : 's have'} no
            video — not counted above:
          </p>
          <ul className="coverage__list">
            {summary.noVideoDevices.map((device) => (
              <li key={device.id}>
                <span className="coverage__camera">{device.display_name || device.name}</span>
                {device.streaming.video_state && (
                  <span className="coverage__since"> — {describeFeedProblem(device)}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
