"""
Test YOLO detection directly on a snapshot
"""
import sys
sys.path.insert(0, '/home/ruth-ai-vas-ms-v2/ai')

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

# Run inference with verbose output
print("\n--- Running YOLO inference ---")
results = model(frame, conf=0.3, classes=[0], verbose=True)

print(f"\nNumber of results: {len(results)}")

if results and len(results) > 0:
    result = results[0]
    if result.boxes is not None and len(result.boxes) > 0:
        print(f"Number of detections: {len(result.boxes)}")
        boxes = result.boxes.xyxy.cpu().numpy()
        confs = result.boxes.conf.cpu().numpy()
        classes = result.boxes.cls.cpu().numpy()

        for i, (box, conf, cls) in enumerate(zip(boxes, confs, classes)):
            x1, y1, x2, y2 = box
            center = ((x1 + x2) / 2, (y1 + y2) / 2)
            print(f"  Detection {i}: class={cls}, conf={conf:.3f}, bbox=[{x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f}], center={center}")
    else:
        print("No detections found")
else:
    print("No results from YOLO")

# Also test on the frame passed through base64 encoding (like the runtime does)
print("\n--- Testing with base64 encoding round-trip ---")
import base64
import io
from PIL import Image

# Encode to base64 (like VAS would)
_, buffer = cv2.imencode('.jpg', frame)
base64_data = base64.b64encode(buffer).decode('utf-8')
print(f"Base64 size: {len(base64_data)} chars")

# Decode like the runtime does
image_bytes = base64.b64decode(base64_data)
image = Image.open(io.BytesIO(image_bytes))
frame_rgb = np.array(image)

# Convert RGB to BGR like runtime does
if len(frame_rgb.shape) == 3 and frame_rgb.shape[2] == 3:
    frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
else:
    frame_bgr = frame_rgb

print(f"Decoded frame shape: {frame_bgr.shape}, dtype: {frame_bgr.dtype}")

# Run inference on the round-tripped frame
results2 = model(frame_bgr, conf=0.3, classes=[0], verbose=False)

if results2 and len(results2) > 0:
    result2 = results2[0]
    if result2.boxes is not None and len(result2.boxes) > 0:
        print(f"Number of detections after base64 round-trip: {len(result2.boxes)}")
    else:
        print("No detections after base64 round-trip")
else:
    print("No results after base64 round-trip")

# Test the geo_fencing inference module directly
print("\n--- Testing geo_fencing inference module ---")
import os
os.environ['MODELS_ROOT'] = '/home/ruth-ai-vas-ms-v2/ai/models'

from models.geo_fencing.v1_0_0.inference import infer

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
