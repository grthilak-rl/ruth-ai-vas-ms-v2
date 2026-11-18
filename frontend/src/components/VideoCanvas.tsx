/**
 * VideoCanvas - Video player with interactive canvas overlay for ROI selection
 */

import { useRef, useEffect, useState } from 'react';
import type { Point } from '../types/geofencing';
import { ROICanvas } from './ROICanvas';
import './VideoCanvas.css';

interface VideoCanvasProps {
  videoUrl: string;
  onMouseDown?: (point: Point) => void;
  onMouseMove?: (point: Point) => void;
  onMouseUp?: (point: Point) => void;
  onClick?: (point: Point) => void;
  corners: Point[];
  isDrawing: boolean;
  mode: 'rectangle' | 'manual';
}

export function VideoCanvas({
  videoUrl,
  onMouseDown,
  onMouseMove,
  onMouseUp,
  onClick,
  corners,
  isDrawing,
  mode
}: VideoCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [currentPoint, setCurrentPoint] = useState<Point | undefined>();
  // Natural-image px -> displayed px. Measured with the container size (on
  // load and resize) instead of reading the image ref during render.
  const [displayScale, setDisplayScale] = useState<{ x: number; y: number } | null>(null);

  const measure = () => {
    if (containerRef.current) {
      const { clientWidth, clientHeight } = containerRef.current;
      setDimensions({ width: clientWidth, height: clientHeight });
    }
    const img = imageRef.current;
    if (img && img.naturalWidth && img.naturalHeight) {
      const rect = img.getBoundingClientRect();
      setDisplayScale({ x: rect.width / img.naturalWidth, y: rect.height / img.naturalHeight });
    }
  };

  useEffect(() => {
    measure();
    window.addEventListener('resize', measure);

    return () => window.removeEventListener('resize', measure);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- measure reads refs only; bind once
  }, []);

  const getCanvasCoordinates = (e: React.MouseEvent<HTMLDivElement>): Point => {
    if (!containerRef.current || !imageRef.current) {
      return { x: 0, y: 0 };
    }

    const imageRect = imageRef.current.getBoundingClientRect();

    // Calculate position relative to image element
    const x = e.clientX - imageRect.left;
    const y = e.clientY - imageRect.top;

    // Scale to image's natural dimensions
    const scaleX = imageRef.current.naturalWidth / imageRect.width;
    const scaleY = imageRef.current.naturalHeight / imageRect.height;

    return {
      x: Math.round(x * scaleX),
      y: Math.round(y * scaleY)
    };
  };

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const point = getCanvasCoordinates(e);
    onMouseDown?.(point);
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    const point = getCanvasCoordinates(e);
    const displayPoint = { x: e.clientX - (imageRef.current?.getBoundingClientRect().left || 0), y: e.clientY - (imageRef.current?.getBoundingClientRect().top || 0) };
    setCurrentPoint(displayPoint);
    onMouseMove?.(point);
  };

  const handleMouseUp = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const point = getCanvasCoordinates(e);
    onMouseUp?.(point);
  };

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const point = getCanvasCoordinates(e);
    onClick?.(point);
  };

  const handleMouseLeave = () => {
    setCurrentPoint(undefined);
  };

  // Convert corners from video coordinates to display coordinates for canvas
  const displayCorners = displayScale
    ? corners.map((p) => ({ x: p.x * displayScale.x, y: p.y * displayScale.y }))
    : corners;

  return (
    <div
      ref={containerRef}
      className="video-canvas"
      style={{ cursor: mode === 'rectangle' ? 'crosshair' : 'pointer' }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onClick={handleClick}
      onMouseLeave={handleMouseLeave}
    >
      <img
        ref={imageRef}
        src={videoUrl}
        alt="Camera feed"
        className="video-canvas__video"
        draggable={false}
        onDragStart={(e) => e.preventDefault()}
        onLoad={measure}
      />

      {dimensions.width > 0 && dimensions.height > 0 && (
        <ROICanvas
          width={dimensions.width}
          height={dimensions.height}
          corners={displayCorners}
          isDrawing={isDrawing}
          currentPoint={currentPoint}
          mode={mode}
        />
      )}
    </div>
  );
}
