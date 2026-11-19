"""
Tank Overflow Detector
Adapted from SimpleTankMonitor for AI Runtime integration

Uses edge detection to find the liquid surface line (topmost horizontal edge).
"""

import cv2
import numpy as np
from datetime import datetime
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


class TankOverflowDetector:
    """
    Tank level detector using edge detection.
    Finds the topmost horizontal line in the ROI as the liquid surface.
    """

    def __init__(self):
        """Initialize tank overflow detector."""
        self.level_history: List[float] = []  # 5 frame smoothing

    def detect_level(self, frame: np.ndarray, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detect liquid level in the tank.

        Args:
            frame: Input frame (BGR format)
            config: Configuration containing:
                - tank_corners: List of 4 [x, y] points (optional)
                - capacity_liters: Tank capacity
                - alert_threshold: Alert threshold percentage

        Returns:
            Dictionary with detection results
        """
        tank_corners = config.get("tank_corners")

        # Default to center 60% if no corners
        if tank_corners is None or len(tank_corners) != 4:
            h, w = frame.shape[:2]
            margin_x = int(w * 0.2)
            margin_y = int(h * 0.2)
            tank_corners = [
                [margin_x, margin_y],
                [w - margin_x, margin_y],
                [w - margin_x, h - margin_y],
                [margin_x, h - margin_y],
            ]

        pts = np.array(tank_corners, dtype=np.int32)
        x, y, w, h = cv2.boundingRect(pts)

        # Clamp to frame bounds
        frame_h, frame_w = frame.shape[:2]
        x = max(0, min(x, frame_w - 1))
        y = max(0, min(y, frame_h - 1))
        w = min(w, frame_w - x)
        h = min(h, frame_h - y)

        if w <= 10 or h <= 10:
            return {
                "level_percent": 0.0,
                "confidence": 0.0,
                "detections": [],
                "timestamp": datetime.now().isoformat(),
            }

        roi = frame[y:y+h, x:x+w]
        if roi.size == 0:
            return {
                "level_percent": 0.0,
                "confidence": 0.0,
                "detections": [],
                "timestamp": datetime.now().isoformat(),
            }

        # ORIGINAL preprocessing
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)  # NOT CLAHE
        blur = cv2.GaussianBlur(gray, (5, 5), 0)

        # ORIGINAL edge detection - FIXED thresholds
        edges = cv2.Canny(blur, 30, 100)  # NOT adaptive

        # ORIGINAL HoughLinesP parameters
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 30, minLineLength=20, maxLineGap=10)

        if lines is None:
            return {
                "level_percent": 0.0,
                "confidence": 0.3,
                "detections": [],
                "timestamp": datetime.now().isoformat(),
            }

        # ORIGINAL: Find TOPMOST horizontal line (NOT longest)
        top_line_y = None
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if abs(y1 - y2) < h * 0.1:  # Roughly horizontal
                if top_line_y is None or y1 < top_line_y:
                    top_line_y = y1  # Take HIGHEST (smallest Y value)

        if top_line_y is None:
            return {
                "level_percent": 0.0,
                "confidence": 0.3,
                "detections": [],
                "timestamp": datetime.now().isoformat(),
            }

        # ORIGINAL calculation
        empty_height = top_line_y
        filled_height = h - empty_height
        percentage = (filled_height / h) * 100
        percentage = max(0, min(100, percentage))

        # ORIGINAL smoothing: 30 frames, simple mean
        self.level_history.append(percentage)
        if len(self.level_history) > 5:
            self.level_history.pop(0)
        smoothed = np.mean(self.level_history)

        return {
            "level_percent": round(smoothed, 2),
            "confidence": 0.8,
            "detections": [{
                "surface_y": int(top_line_y),
                "bbox": [int(x), int(y), int(x + w), int(y + h)],
                "confidence": 0.8
            }],
            "timestamp": datetime.now().isoformat(),
        }
