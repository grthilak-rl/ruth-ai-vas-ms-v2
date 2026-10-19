import { Link } from 'react-router-dom';
import type { Incident, Violation, ViolationStatus } from '../../state/api';
import { getConfidenceDisplay, useViolationsQuery } from '../../state';
import { NO_TYPE_DETAIL } from '../../utils/violationLabels';
import { cameraHeadline, cameraNumber, formatIncidentSpan, severityOrDefault } from '../../utils/violationDisplay';
import { SeverityBadge } from './SeverityBadge';
import { StatusBadge } from './StatusBadge';
import { SnapshotThumbnail } from './SnapshotThumbnail';
import './IncidentCard.css';

export type IncidentAction = 'review' | 'dismiss';

interface IncidentCardProps {
  incident: Incident;
  /** Status filter in force, so the expanded list shows the same members */
  statuses: ViolationStatus[];
  /** Card action: applies to the incident's open violations (parent confirms) */
  onGroupAction: (incident: Incident, action: IncidentAction) => void;
  /** Row action on one member */
  onMemberAction: (incident: Incident, violation: Violation, action: IncidentAction) => void;
  isPending?: boolean;
  error?: string | null;
  /** Expanded to list its violations (kept in the URL by the page) */
  expanded: boolean;
  onToggleExpand: (incident: Incident) => void;
  /** Bulk selection; the checkbox shows only while something is open */
  selected?: boolean;
  onToggleSelect?: (incident: Incident) => void;
}

function formatRelativeTime(timestamp: string): string {
  const diffMinutes = Math.floor((Date.now() - new Date(timestamp).getTime()) / 60000);
  if (diffMinutes < 1) return 'Just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return new Date(timestamp).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function formatClock(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  });
}

/** The cropped inferred frame when there is one; else the scene snapshot. */
function Thumbnail({ violation, alt }: { violation: Violation; alt: string }) {
  const evidence = violation.evidence;
  if (evidence?.frame_thumb_url) {
    return <img src={evidence.frame_thumb_url} alt={alt} className="incident-card__thumb-img" loading="lazy" />;
  }
  return (
    <SnapshotThumbnail
      snapshotUrl={evidence?.snapshot_url ?? null}
      snapshotStatus={evidence?.snapshot_status ?? 'pending'}
      alt={alt}
    />
  );
}

/** 🎞 when a clip is ready to play. */
function ClipIcon({ title }: { title: string }) {
  return (
    <span className="incident-card__clip" role="img" aria-label={title} title={title}>
      🎞
    </span>
  );
}

/**
 * Incident Card — repeated violations of one type on one camera.
 *
 * Shows the latest violation's cropped frame, the camera by area/side and
 * number, the rule's severity, how many violations and over what span, and
 * a clip icon when any has a clip. The card's actions apply to the
 * incident's open violations (the parent confirms the count first); each
 * violation keeps its own actions in the expanded list.
 *
 * No "New" badge: the list shows open violations by default, so it said
 * the same thing on every card. A status badge appears only once nothing
 * in the incident is open.
 */
export function IncidentCard({
  incident,
  statuses,
  onGroupAction,
  onMemberAction,
  isPending = false,
  error = null,
  expanded,
  onToggleExpand,
  selected = false,
  onToggleSelect,
}: IncidentCardProps) {
  const latest = incident.representative;
  const headline = cameraHeadline(incident);
  const typeLabel = incident.detail_label ?? incident.type_label;
  const severity = severityOrDefault(incident.severity);
  const openCount = incident.open_count;

  return (
    <article
      className={`incident-card incident-card--${severity}${selected ? ' incident-card--selected' : ''}`}
      aria-label={`${typeLabel} on ${headline}, ${incident.count} violation${incident.count === 1 ? '' : 's'}`}
    >
      <div className="incident-card__main">
        {onToggleSelect && (
          <div className="incident-card__select">
            {openCount > 0 && (
              <input
                type="checkbox"
                checked={selected}
                onChange={() => onToggleSelect(incident)}
                aria-label={`Select ${typeLabel} on ${headline} (${openCount} open)`}
              />
            )}
          </div>
        )}
        <Link to={`/alerts/${latest.id}`} className="incident-card__thumb" aria-label="Open the latest violation">
          <Thumbnail violation={latest} alt={`${typeLabel} on ${headline}`} />
        </Link>

        <div className="incident-card__content">
          <div className="incident-card__header">
            <h3 className="incident-card__camera">
              <span className="incident-card__camera-name">{headline}</span>
              <span className="incident-card__camera-number">#{cameraNumber(incident)}</span>
            </h3>
            <div className="incident-card__badges">
              {incident.has_clip && <ClipIcon title="A clip is available" />}
              <SeverityBadge severity={severity} />
              {openCount === 0 && <StatusBadge status={latest.status} />}
            </div>
          </div>

          <div className="incident-card__type">
            <span className="incident-card__type-detail">{typeLabel}</span>
            {incident.detail_label && <span className="incident-card__type-family">{incident.type_label}</span>}
          </div>

          <div className="incident-card__meta">
            <span className="incident-card__count">
              {incident.count} violation{incident.count === 1 ? '' : 's'}
              {openCount > 0 && openCount < incident.count && ` · ${openCount} open`}
            </span>
            <span>{formatIncidentSpan(incident.first_at, incident.last_at)}</span>
            <span>{formatRelativeTime(incident.last_at)}</span>
            <span className="incident-card__confidence">
              Latest: {getConfidenceDisplay(latest.confidence)} confidence
            </span>
          </div>

          {error && (
            <div className="incident-card__error" role="alert">
              {error}
            </div>
          )}

          <div className="incident-card__actions">
            <Link to={`/alerts/${latest.id}`} className="incident-card__action incident-card__action--view">
              View latest
            </Link>
            {openCount > 0 && (
              <>
                <button
                  type="button"
                  className="incident-card__action incident-card__action--review"
                  onClick={() => onGroupAction(incident, 'review')}
                  disabled={isPending}
                >
                  {openCount > 1 ? `Mark ${openCount} reviewed` : 'Mark reviewed'}
                </button>
                <button
                  type="button"
                  className="incident-card__action incident-card__action--dismiss"
                  onClick={() => onGroupAction(incident, 'dismiss')}
                  disabled={isPending}
                >
                  {openCount > 1 ? `Dismiss ${openCount}` : 'Dismiss'}
                </button>
              </>
            )}
            {incident.count > 1 && (
              <button
                type="button"
                className="incident-card__action incident-card__action--expand"
                onClick={() => onToggleExpand(incident)}
                aria-expanded={expanded}
              >
                {expanded ? 'Hide violations ▴' : `Show all ${incident.count} ▾`}
              </button>
            )}
          </div>
        </div>
      </div>

      {expanded && (
        <IncidentMembers
          incident={incident}
          statuses={statuses}
          onMemberAction={(violation, action) => onMemberAction(incident, violation, action)}
        />
      )}
    </article>
  );
}

interface IncidentMembersProps {
  incident: Incident;
  statuses: ViolationStatus[];
  onMemberAction: (violation: Violation, action: IncidentAction) => void;
}

/**
 * The incident's violations, newest first, each with its own actions.
 *
 * Fetched with the incident's exact boundaries (camera, type, first/last
 * timestamps as the backend sent them) and the page's status filter, so the
 * rows are exactly the incident's members.
 */
function IncidentMembers({ incident, statuses, onMemberAction }: IncidentMembersProps) {
  const { data, isLoading, isError } = useViolationsQuery({
    camera_id: incident.camera_id,
    type: incident.type,
    type_detail: incident.type_detail ?? NO_TYPE_DETAIL,
    since: incident.first_at,
    until: incident.last_at,
    status: statuses.length ? statuses : undefined,
    sort_by: 'timestamp',
    sort_order: 'desc',
    limit: 500,
  });

  if (isLoading) return <div className="incident-members incident-members--loading">Loading violations…</div>;
  if (isError || !data) {
    return <div className="incident-members incident-members--error">Couldn't load the violations.</div>;
  }

  const members = [...data.items].sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  );

  return (
    <ul className="incident-members" aria-label="Violations in this incident">
      {members.map((violation) => {
        const isOpen = violation.status === 'open';
        const hasClip = violation.evidence?.bookmark_status === 'ready';
        return (
          <li key={violation.id} className="incident-members__row">
            <span className="incident-members__time">{formatClock(violation.timestamp)}</span>
            <span className="incident-members__confidence">
              {getConfidenceDisplay(violation.confidence)} confidence
            </span>
            {hasClip && <ClipIcon title="Clip available" />}
            {!isOpen && <StatusBadge status={violation.status} />}
            <span className="incident-members__actions">
              <Link to={`/alerts/${violation.id}`} className="incident-members__action">
                View
              </Link>
              {isOpen && (
                <>
                  <button
                    type="button"
                    className="incident-members__action"
                    onClick={() => onMemberAction(violation, 'review')}
                  >
                    Mark reviewed
                  </button>
                  <button
                    type="button"
                    className="incident-members__action incident-members__action--dismiss"
                    onClick={() => onMemberAction(violation, 'dismiss')}
                  >
                    Dismiss
                  </button>
                </>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
