"""
Test YOLO detection and geo_fencing module directly
"""
import sys
sys.path.insert(0, '/home/ruth-ai-vas-ms-v2/ai')
sys.path.insert(0, '/home/ruth-ai-vas-ms-v2/ai/models/geo_fencing/1.0.0')

import cv2
import numpy as np
from ultralytics import YOLO

# Load the snapshot
image_path = "/tmp/test_snapshot.jpg"
frame = cv2.imread(image_path)
print(f"Frame shape: {frame.shape}, dtype: {frame.dtype}")

# Test with yolov8n.pt
weights_path = "/home/ruth-ai-vas-ms-v2/ai/models/geo_fencing/1.0.0/weights/yolov8n.pt"
print(f"\nLoading model from {weights_path}")
model = YOLO(weights_path)

# Run inference
results = model(frame, conf=0.3, classes=[0], verbose=True)

print(f"\nNumber of results: {len(results)}")

if results and len(results) > 0:
    result = results[0]
    if result.boxes is not None and len(result.boxes) > 0:
        print(f"Number of detections: {len(result.boxes)}")
        boxes = result.boxes.xyxy.cpu().numpy()
        confs = result.boxes.conf.cpu().numpy()

        for i, (box, conf) in enumerate(zip(boxes, confs)):
            x1, y1, x2, y2 = box
            center = ((x1 + x2) / 2, (y1 + y2) / 2)
            print(f"  Detection {i}: conf={conf:.3f}, bbox=[{x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f}], center=({center[0]:.0f},{center[1]:.0f})")

            # Check if inside zone
            zone_points = [[654, 584], [877, 662], [851, 1042], [497, 903]]
            print(f"  Zone points: {zone_points}")

            # Point in polygon check
            x, y = center
            n = len(zone_points)
            inside = False

            p1x, p1y = zone_points[0]
            for i in range(1, n + 1):
                p2x, p2y = zone_points[i % n]
                if y > min(p1y, p2y):
                    if y <= max(p1y, p2y):
                        if x <= max(p1x, p2x):
                            if p1y != p2y:
                                xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                            if p1x == p2x or x <= xinters:
                                inside = not inside
                p1x, p1y = p2x, p2y

            print(f"  Person center ({center[0]:.0f},{center[1]:.0f}) inside zone: {inside}")
    else:
        print("No detections found")

# Test the geo_fencing inference module directly
print("\n--- Testing geo_fencing inference module ---")
from inference import infer

test_config = {
    "zones": [{
        "id": "zone_1",
        "name": "Restricted Zone",
        "type": "restricted",
        "points": [[654, 584], [877, 662], [851, 1042], [497, 903]]
    }]
}

result = infer(frame, config=test_config)
print(f"Violation detected: {result.get('violation_detected')}")
print(f"Detection count: {len(result.get('detections', []))}")
print(f"Detections: {result.get('detections')}")
print(f"Metadata: {result.get('metadata')}")
