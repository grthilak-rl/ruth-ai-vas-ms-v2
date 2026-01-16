/**
 * Video Components (E10)
 *
 * Real-time video layer with detection overlays.
 * Isolated from core UI - failures here never block operator workflows.
 */

export { LiveVideoPlayer } from './LiveVideoPlayer';
export { VideoOverlay } from './VideoOverlay';
export { VideoErrorBoundary } from './VideoErrorBoundary';
export { useVideoStream } from './useVideoStream';
export type { VideoStreamState, VideoError } from './useVideoStream';
