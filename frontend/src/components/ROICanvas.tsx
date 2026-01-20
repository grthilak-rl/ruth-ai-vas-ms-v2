/**
 * ROICanvas - Canvas overlay for drawing ROI rectangles and polygons
 */

import { useRef, useEffect } from 'react';
import type { Point } from '../types/geofencing';

interface ROICanvasProps {
  width: number;
  height: number;
  corners: Point[];
  isDrawing: boolean;
  currentPoint?: Point;
  mode: 'rectangle' | 'manual';
}

export const ROICanvas: React.FC<ROICanvasProps> = ({
  width,
  height,
  corners,
  isDrawing,
  currentPoint,
  mode
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear canvas
    ctx.clearRect(0, 0, width, height);

    if (corners.length === 0) return;

    // Draw the ROI
    ctx.strokeStyle = '#10b981'; // Green
    ctx.fillStyle = 'rgba(16, 185, 129, 0.2)'; // Green with transparency
    ctx.lineWidth = 3;

    if (mode === 'rectangle' && corners.length >= 2) {
      // Draw rectangle from first corner to last (or current point if drawing)
      const start = corners[0];
      const end = currentPoint && isDrawing ? currentPoint : corners[corners.length - 1];

      ctx.beginPath();
      ctx.rect(
        Math.min(start.x, end.x),
        Math.min(start.y, end.y),
        Math.abs(end.x - start.x),
        Math.abs(end.y - start.y)
      );
      ctx.fill();
      ctx.stroke();

      // Draw corner handles
      [start, { x: end.x, y: start.y }, end, { x: start.x, y: end.y }].forEach((point, index) => {
        ctx.fillStyle = '#10b981';
        ctx.beginPath();
        ctx.arc(point.x, point.y, 6, 0, 2 * Math.PI);
        ctx.fill();

        // Add corner labels
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 12px sans-serif';
        const labels = ['1', '2', '3', '4'];
        ctx.fillText(labels[index], point.x - 4, point.y + 4);
      });

    } else if (mode === 'manual') {
      // Draw polygon for manual mode
      ctx.beginPath();
      ctx.moveTo(corners[0].x, corners[0].y);

      for (let i = 1; i < corners.length; i++) {
        ctx.lineTo(corners[i].x, corners[i].y);
      }

      // If currently drawing and have current point, draw line to it
      if (isDrawing && currentPoint && corners.length < 4) {
        ctx.lineTo(currentPoint.x, currentPoint.y);
      }

      // Close the polygon if we have all 4 corners
      if (corners.length === 4) {
        ctx.closePath();
        ctx.fill();
      }

      ctx.stroke();

      // Draw corner points with numbers
      corners.forEach((point, index) => {
        ctx.fillStyle = '#10b981';
        ctx.beginPath();
        ctx.arc(point.x, point.y, 8, 0, 2 * Math.PI);
        ctx.fill();

        // Add number label
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 14px sans-serif';
        ctx.fillText((index + 1).toString(), point.x - 5, point.y + 5);
      });

      // Draw next point indicator
      if (corners.length < 4 && currentPoint) {
        ctx.fillStyle = 'rgba(16, 185, 129, 0.5)';
        ctx.beginPath();
        ctx.arc(currentPoint.x, currentPoint.y, 6, 0, 2 * Math.PI);
        ctx.fill();
      }
    }

    // Draw crosshair at current point when hovering
    if (currentPoint && !isDrawing && corners.length < 4) {
      ctx.strokeStyle = '#10b981';
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 5]);

      // Horizontal line
      ctx.beginPath();
      ctx.moveTo(0, currentPoint.y);
      ctx.lineTo(width, currentPoint.y);
      ctx.stroke();

      // Vertical line
      ctx.beginPath();
      ctx.moveTo(currentPoint.x, 0);
      ctx.lineTo(currentPoint.x, height);
      ctx.stroke();

      ctx.setLineDash([]);
    }

  }, [corners, isDrawing, currentPoint, mode, width, height]);

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        pointerEvents: 'none'
      }}
    />
  );
};
