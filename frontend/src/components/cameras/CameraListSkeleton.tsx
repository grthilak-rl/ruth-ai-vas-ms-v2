import './CameraListSkeleton.css';

/**
 * Camera List Skeleton (F4 §7.4)
 *
 * Loading placeholder for camera grid.
 */
export function CameraListSkeleton() {
  return (
    <div className="camera-list-skeleton">
      <div className="camera-list-skeleton__header">
        <div className="camera-list-skeleton__title" />
      </div>

      <div className="camera-list-skeleton__grid">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="camera-list-skeleton__card">
            <div className="camera-list-skeleton__thumbnail" />
            <div className="camera-list-skeleton__info">
              <div className="camera-list-skeleton__name" />
              <div className="camera-list-skeleton__status" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
