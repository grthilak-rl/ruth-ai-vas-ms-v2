import { Link } from 'react-router-dom';
import './CameraNotFound.css';

/**
 * Camera Not Found Component (F4 §7.6)
 *
 * Displayed when a camera ID is invalid or the camera
 * no longer exists. Provides clear navigation back to cameras.
 *
 * Per F3 Constraints:
 * - No technical IDs shown to user
 * - No error codes
 * - Clear, actionable message
 */
export function CameraNotFound() {
  return (
    <div className="camera-not-found">
      <div className="camera-not-found__content">
        <h1 className="camera-not-found__title">
          Camera Not Found
        </h1>
        <p className="camera-not-found__message">
          This camera may have been removed or the link is incorrect.
        </p>
        <Link to="/cameras" className="camera-not-found__link">
          Back to Cameras
        </Link>
      </div>
    </div>
  );
}
