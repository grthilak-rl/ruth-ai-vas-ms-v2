#!/home/ruth-ai-vas-ms-v2/ai/venv/bin/python3
"""
Test Tank Overflow Detection with a static image
Useful for testing without a webcam
"""

import cv2
import numpy as np
import sys
import os

# Add AI models path
sys.path.insert(0, '/home/ruth-ai-vas-ms-v2/ai/models/tank_overflow_monitoring/1.0.0')
from tank_detector import TankOverflowDetector


def test_with_image(image_path, corners=None):
    """
    Test tank detection with a static image

    Args:
        image_path: Path to image file
        corners: List of 4 [x, y] corner points, or None to use auto-detection
    """
    print("\n" + "="*60)
    print("Tank Overflow Detection - Image Test")
    print("="*60)

    # Load image
    if not os.path.exists(image_path):
        print(f"✗ Image not found: {image_path}")
        return

    frame = cv2.imread(image_path)
    if frame is None:
        print(f"✗ Failed to load image: {image_path}")
        return

    print(f"✓ Image loaded: {image_path}")
    print(f"  Size: {frame.shape[1]}x{frame.shape[0]}")

    # Create detector
    detector = TankOverflowDetector()

    # If no corners provided, use center region
    if corners is None:
        h, w = frame.shape[:2]
        margin_x = int(w * 0.3)
        margin_y = int(h * 0.3)
        corners = [
            [margin_x, margin_y],  # top-left
            [w - margin_x, margin_y],  # top-right
            [w - margin_x, h - margin_y],  # bottom-right
            [margin_x, h - margin_y],  # bottom-left
        ]
        print(f"  Using auto-detected region (center 40% of image)")
    else:
        print(f"  Using provided corners")

    # Configuration
    config = {
        "tank_corners": corners,
        "capacity_liters": 1.0,  # 1 liter for testing
        "alert_threshold": 90
    }

    # Run detection
    print("\nRunning detection...")
    result = detector.detect_level(frame, config)

    # Print results
    print("\n" + "-"*60)
    print("DETECTION RESULTS:")
    print("-"*60)
    print(f"  Level: {result['level_percent']:.1f}%")
    print(f"  Confidence: {result['confidence']:.2f}")
    print(f"  Volume: {result['level_percent'] * 10:.0f}ml (assuming 1L capacity)")
    print(f"  Timestamp: {result['timestamp']}")

    if result['detections']:
        print(f"\n  Surface detected at Y: {result['detections'][0]['surface_y']}")
        print(f"  Bounding box: {result['detections'][0]['bbox']}")
    else:
        print("\n  No surface detected")

    # Create visualization
    display = frame.copy()

    # Draw tank region
    pts = np.array(corners, dtype=np.int32)
    cv2.polylines(display, [pts], True, (0, 255, 0), 2)

    # Label corners
    for i, corner in enumerate(corners):
        cv2.circle(display, tuple(corner), 5, (0, 255, 0), -1)
        cv2.putText(display, str(i+1),
                   (corner[0]+10, corner[1]+10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    # Draw liquid surface if detected
    if result['detections']:
        surface_y = result['detections'][0]['surface_y']
        x1 = corners[0][0]
        x2 = corners[1][0]
        y = corners[0][1] + surface_y
        cv2.line(display, (x1, y), (x2, y), (0, 0, 255), 3)
        cv2.putText(display, "Liquid Surface",
                   (x1 + 10, y - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    # Add info panel
    level = result['level_percent']
    if level >= 90:
        color = (0, 0, 255)  # Red
        status = "ALERT!"
    elif level >= 75:
        color = (0, 165, 255)  # Orange
        status = "High"
    elif level >= 50:
        color = (0, 255, 255)  # Yellow
        status = "Medium"
    else:
        color = (0, 255, 0)  # Green
        status = "Normal"

    cv2.rectangle(display, (10, 10), (350, 120), (0, 0, 0), -1)
    cv2.rectangle(display, (10, 10), (350, 120), (255, 255, 255), 2)
    cv2.putText(display, f"Level: {level:.1f}%",
               (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    cv2.putText(display, f"Status: {status}",
               (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    cv2.putText(display, f"Confidence: {result['confidence']:.2f}",
               (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    # Save result
    output_path = image_path.replace('.', '_result.')
    cv2.imwrite(output_path, display)
    print(f"\n✓ Result image saved: {output_path}")
    print("="*60 + "\n")

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 test_tank_image.py <image_path> [x1,y1,x2,y2,x3,y3,x4,y4]")
        print("\nExample:")
        print("  python3 test_tank_image.py mug_photo.jpg")
        print("  python3 test_tank_image.py mug_photo.jpg 100,50,300,50,300,400,100,400")
        sys.exit(1)

    image_path = sys.argv[1]

    # Parse corners if provided
    corners = None
    if len(sys.argv) > 2:
        coords = list(map(int, sys.argv[2].split(',')))
        if len(coords) == 8:
            corners = [
                [coords[0], coords[1]],
                [coords[2], coords[3]],
                [coords[4], coords[5]],
                [coords[6], coords[7]]
            ]

    test_with_image(image_path, corners)
