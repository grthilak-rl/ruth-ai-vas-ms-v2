import { useState, useCallback } from 'react';
import type { ViolationEvidence } from '../../state/api';
import './EvidenceViewer.css';

// Default evidence when backend doesn't provide one
const DEFAULT_EVIDENCE: ViolationEvidence = {
  snapshot_id: null,
  snapshot_url: null,
  snapshot_status: 'pending',
  bookmark_id: null,
  bookmark_url: null,
  bookmark_status: 'pending',
};

interface EvidenceViewerProps {
  evidence?: ViolationEvidence;
  cameraName: string;
  timestamp: string;
}

/**
 * Format timestamp for display (F6 §12.1)
 */
function formatTimestamp(isoTimestamp: string): string {
  const date = new Date(isoTimestamp);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  });
}

/**
 * Evidence Viewer Component (F4 §6, F3 Flow 2)
 *
 * Displays snapshot and video evidence for a violation.
 *
 * Per F3 Flow 2:
 * - Snapshot displays immediately if available
 * - Video loads on demand (never auto-load)
 * - Evidence failure doesn't block actions
 *
 * Evidence States (F6 §3.4):
 * - pending: "Preparing evidence..."
 * - processing: Same as pending
 * - ready: Enable rendering
 * - failed: "Evidence unavailable"
 *
 * HARD RULES:
 * - F3: Video must never auto-load
 * - F3: No blocking while evidence loads
 * - Snapshot and video are independent
 */
export function EvidenceViewer({
  evidence: evidenceProp,
  cameraName,
  timestamp,
}: EvidenceViewerProps) {
  const [isVideoPlaying, setIsVideoPlaying] = useState(false);
  const [videoError, setVideoError] = useState(false);

  // Use default evidence if not provided
  const evidence = evidenceProp ?? DEFAULT_EVIDENCE;

  // Determine snapshot availability
  const isSnapshotReady = evidence.snapshot_status === 'ready' && evidence.snapshot_url;
  const isSnapshotPreparing = evidence.snapshot_status === 'pending' || evidence.snapshot_status === 'processing';
  const isSnapshotFailed = evidence.snapshot_status === 'failed' || (!evidence.snapshot_url && evidence.snapshot_status === 'ready');

  // Determine video availability
  const isVideoReady = evidence.bookmark_status === 'ready' && evidence.bookmark_url;
  const isVideoPreparing = evidence.bookmark_status === 'pending' || evidence.bookmark_status === 'processing';
  const isVideoFailed = evidence.bookmark_status === 'failed';

  // Handle play video click
  const handlePlayVideo = useCallback(() => {
    if (isVideoReady) {
      setIsVideoPlaying(true);
      setVideoError(false);
    }
  }, [isVideoReady]);

  // Handle video error
  const handleVideoError = useCallback(() => {
    setVideoError(true);
    setIsVideoPlaying(false);
  }, []);

  // Handle close video
  const handleCloseVideo = useCallback(() => {
    setIsVideoPlaying(false);
  }, []);

  // No evidence at all
  const hasNoEvidence = isSnapshotFailed && (isVideoFailed || (!evidence.bookmark_url && !isVideoPreparing));

  return (
    <div className="evidence-viewer">
      {/* Video player overlay (when playing) */}
      {isVideoPlaying && evidence.bookmark_url && (
        <div className="evidence-viewer__video-container">
          <div className="evidence-viewer__video-header">
            <span className="evidence-viewer__video-title">Evidence Clip</span>
            <button
              type="button"
              className="evidence-viewer__video-close"
              onClick={handleCloseVideo}
              aria-label="Close video"
            >
              ×
            </button>
          </div>
          {videoError ? (
            <div className="evidence-viewer__video-error">
              <p>Video playback failed</p>
              <button
                type="button"
                className="evidence-viewer__retry"
                onClick={() => {
                  setVideoError(false);
                  setIsVideoPlaying(true);
                }}
              >
                Retry
              </button>
            </div>
          ) : (
            <video
              className="evidence-viewer__video"
              src={evidence.bookmark_url}
              controls
              autoPlay
              onError={handleVideoError}
            >
              Your browser does not support video playback.
            </video>
          )}
        </div>
      )}

      {/* Snapshot display */}
      <div className="evidence-viewer__snapshot">
        {isSnapshotReady && evidence.snapshot_url ? (
          <img
            src={evidence.snapshot_url}
            alt={`Detection snapshot from ${cameraName}`}
            className="evidence-viewer__image"
          />
        ) : isSnapshotPreparing ? (
          <div className="evidence-viewer__placeholder evidence-viewer__placeholder--preparing">
            <div className="evidence-viewer__placeholder-content">
              <span className="evidence-viewer__placeholder-icon">⏳</span>
              <p className="evidence-viewer__placeholder-text">Preparing evidence...</p>
            </div>
          </div>
        ) : hasNoEvidence ? (
          <div className="evidence-viewer__placeholder evidence-viewer__placeholder--unavailable">
            <div className="evidence-viewer__placeholder-content">
              <span className="evidence-viewer__placeholder-icon">📷</span>
              <p className="evidence-viewer__placeholder-text">Evidence not available</p>
              <p className="evidence-viewer__placeholder-detail">
                Detection occurred at {formatTimestamp(timestamp)} on {cameraName}.
              </p>
            </div>
          </div>
        ) : (
          <div className="evidence-viewer__placeholder evidence-viewer__placeholder--unavailable">
            <div className="evidence-viewer__placeholder-content">
              <span className="evidence-viewer__placeholder-icon">⚠</span>
              <p className="evidence-viewer__placeholder-text">Snapshot unavailable</p>
            </div>
          </div>
        )}

        {/* Play video button (overlay on snapshot) */}
        {!isVideoPlaying && (isVideoReady || isVideoPreparing) && (
          <div className="evidence-viewer__play-overlay">
            {isVideoReady ? (
              <button
                type="button"
                className="evidence-viewer__play-button"
                onClick={handlePlayVideo}
              >
                ▶ Play Evidence
              </button>
            ) : isVideoPreparing ? (
              <span className="evidence-viewer__play-preparing">
                Preparing video...
              </span>
            ) : null}
          </div>
        )}
      </div>

      {/* Timestamp footer */}
      <div className="evidence-viewer__footer">
        <span className="evidence-viewer__timestamp">
          {formatTimestamp(timestamp)}
        </span>
        {isVideoFailed && !isVideoPreparing && (
          <span className="evidence-viewer__video-status">
            Video clip unavailable
          </span>
        )}
      </div>
    </div>
  );
}
