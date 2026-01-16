import { Component, type ReactNode, type ErrorInfo } from 'react';

interface VideoErrorBoundaryProps {
  children: ReactNode;
  /** Fallback to render when video crashes */
  fallback?: ReactNode;
  /** Device name for error message */
  deviceName?: string;
}

interface VideoErrorBoundaryState {
  hasError: boolean;
}

/**
 * Video-Specific Error Boundary (E10)
 *
 * Isolates video rendering errors from the rest of the UI.
 *
 * Per E10 Spec:
 * - Video failures must never escalate to global error state
 * - Camera screens remain usable during video downtime
 *
 * HARD RULE: Video errors are contained here and never propagate upward.
 */
export class VideoErrorBoundary extends Component<
  VideoErrorBoundaryProps,
  VideoErrorBoundaryState
> {
  constructor(props: VideoErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): VideoErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log video errors separately (never surface to global logging)
    console.warn('[VideoErrorBoundary] Video component error:', error.message);
    console.debug('[VideoErrorBoundary] Stack:', errorInfo.componentStack);
  }

  handleRetry = (): void => {
    this.setState({ hasError: false });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      // Use custom fallback if provided
      if (this.props.fallback) {
        return this.props.fallback;
      }

      // Default non-alarming fallback
      return (
        <div className="video-error-fallback">
          <p className="video-error-fallback__message">
            Video temporarily unavailable
          </p>
          <button
            type="button"
            className="video-error-fallback__retry"
            onClick={this.handleRetry}
          >
            Try Again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
