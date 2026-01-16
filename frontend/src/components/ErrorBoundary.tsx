import { Component, type ReactNode, type ErrorInfo } from 'react';
import './ErrorBoundary.css';

interface ErrorBoundaryProps {
  children: ReactNode;
  /** Optional fallback to render instead of default */
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

/**
 * Root-level Error Boundary (E1, E9)
 *
 * Catches render/runtime errors and displays a neutral fallback message.
 *
 * Per E1 spec:
 * - No error codes displayed
 * - No stack traces displayed
 *
 * Per E9 spec:
 * - Retry capability (via Reset button)
 * - No dead ends (always has an action)
 * - Blame-free language
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log error to console for debugging purposes only
    console.error('[ErrorBoundary] Caught error:', error);
    console.error('[ErrorBoundary] Component stack:', errorInfo.componentStack);
  }

  handleRetry = (): void => {
    this.setState({ hasError: false });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      // Allow custom fallback
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="error-boundary-fallback">
          <div className="error-boundary-fallback__content">
            <h1 className="error-boundary-fallback__title">
              Something went wrong
            </h1>
            <p className="error-boundary-fallback__message">
              An unexpected error occurred. You can try again or return to the home page.
            </p>
            <div className="error-boundary-fallback__actions">
              <button
                type="button"
                className="error-boundary-fallback__retry"
                onClick={this.handleRetry}
              >
                Try Again
              </button>
              <a href="/" className="error-boundary-fallback__home">
                Go to Home
              </a>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
