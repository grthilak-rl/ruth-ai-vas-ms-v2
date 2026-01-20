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

  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        const { clientWidth, clientHeight } = containerRef.current;
        setDimensions({ width: clientWidth, height: clientHeight });
      }
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);

    return () => window.removeEventListener('resize', updateDimensions);
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

  const getDisplayCoordinates = (point: Point): Point => {
    if (!imageRef.current) return point;

    const imageRect = imageRef.current.getBoundingClientRect();
    const scaleX = imageRect.width / imageRef.current.naturalWidth;
    const scaleY = imageRect.height / imageRef.current.naturalHeight;

    return {
      x: point.x * scaleX,
      y: point.y * scaleY
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
  const displayCorners = corners.map(getDisplayCoordinates);

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
        onLoad={() => {
          if (imageRef.current && containerRef.current) {
            const { clientWidth, clientHeight } = containerRef.current;
            setDimensions({ width: clientWidth, height: clientHeight });
          }
        }}
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
