import type { EvidenceStatus } from '../../state/api';
import './SnapshotThumbnail.css';

interface SnapshotThumbnailProps {
  snapshotUrl: string | null;
  snapshotStatus: EvidenceStatus;
  alt: string;
}

/**
 * Snapshot Thumbnail Component (F4/F6-aligned)
 *
 * Displays evidence snapshot with proper fallbacks.
 *
 * Per F6 §3.4:
 * - pending/processing: "Preparing..." placeholder
 * - ready: Show image
 * - failed: "Unavailable" placeholder
 *
 * HARD RULE: MUST NOT attempt to load image if status is not 'ready'.
 */
export function SnapshotThumbnail({
  snapshotUrl,
  snapshotStatus,
  alt,
}: SnapshotThumbnailProps) {
  // F6 §3.4: Only show image if status is 'ready' and URL exists
  if (snapshotStatus === 'ready' && snapshotUrl) {
    return (
      <img
        src={snapshotUrl}
        alt={alt}
        className="snapshot-thumbnail snapshot-thumbnail--ready"
        loading="lazy"
      />
    );
  }

  // Pending or processing
  if (snapshotStatus === 'pending' || snapshotStatus === 'processing') {
    return (
      <div className="snapshot-thumbnail snapshot-thumbnail--preparing">
        <span className="snapshot-thumbnail__text">Preparing...</span>
      </div>
    );
  }

  // Failed or no URL
  return (
    <div className="snapshot-thumbnail snapshot-thumbnail--unavailable">
      <span className="snapshot-thumbnail__text">No Image</span>
    </div>
  );
}
