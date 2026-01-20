"""
Debug script to test why inference returns 0 detections
"""
import sys
sys.path.insert(0, '/home/ruth-ai-vas-ms-v2/ai')

import os
os.environ['MODELS_ROOT'] = '/home/ruth-ai-vas-ms-v2/ai/models'

import requests
import base64
from PIL import Image
import io
import numpy as np

# Get a snapshot from VAS
VAS_URL = "http://10.30.250.245:8085"

# First, get auth token
auth_response = requests.post(
    f"{VAS_URL}/v2/auth/token",
    json={
        "client_id": "vas-portal",
        "client_secret": "vas-portal-secret-2024"
    }
)
token = auth_response.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Get active streams
streams_response = requests.get(f"{VAS_URL}/v2/streams", headers=headers)
streams = streams_response.json().get("items", [])

print(f"Found {len(streams)} streams")

if not streams:
    print("No streams found. Please start a stream first.")
    sys.exit(1)

# Find a LIVE stream
live_stream = None
for s in streams:
    if s.get("state", "").lower() == "live":
        live_stream = s
        break

if not live_stream:
    print(f"No live streams found. States: {[s.get('state') for s in streams]}")
    # Use first stream anyway for testing
    live_stream = streams[0]

stream_id = live_stream["id"]
print(f"Using stream {stream_id}, state: {live_stream.get('state')}")

# Create a snapshot
snapshot_response = requests.post(
    f"{VAS_URL}/v2/streams/{stream_id}/snapshots",
    headers=headers,
    json={"label": "debug_test"}
)

if snapshot_response.status_code != 201:
    print(f"Failed to create snapshot: {snapshot_response.status_code}")
    print(snapshot_response.text)
    sys.exit(1)

snapshot = snapshot_response.json()
snapshot_id = snapshot["id"]
print(f"Created snapshot: {snapshot_id}")

# Wait for it to be ready
import time
for _ in range(10):
    snap_resp = requests.get(f"{VAS_URL}/v2/snapshots/{snapshot_id}", headers=headers)
    snap_data = snap_resp.json()
    if snap_data.get("status", "").lower() in ["ready", "completed"]:
        print(f"Snapshot ready: {snap_data.get('status')}")
        break
    time.sleep(0.5)

# Download image
img_resp = requests.get(f"{VAS_URL}/v2/snapshots/{snapshot_id}/image", headers=headers)
if img_resp.status_code != 200:
    print(f"Failed to download image: {img_resp.status_code}")
    sys.exit(1)

image_bytes = img_resp.content
print(f"Downloaded {len(image_bytes)} bytes")

# Save for inspection
with open("/tmp/debug_frame.jpg", "wb") as f:
    f.write(image_bytes)
print("Saved to /tmp/debug_frame.jpg")

# Decode the image
img = Image.open(io.BytesIO(image_bytes))
print(f"Image size: {img.size}, mode: {img.mode}")

# Convert to numpy array (BGR for OpenCV)
import cv2
frame_rgb = np.array(img)
if len(frame_rgb.shape) == 3 and frame_rgb.shape[2] == 3:
    frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
else:
    frame_bgr = frame_rgb

print(f"Frame shape: {frame_bgr.shape}, dtype: {frame_bgr.dtype}")

# Now test YOLO directly
from ultralytics import YOLO

weights_path = "/home/ruth-ai-vas-ms-v2/ai/models/geo_fencing/1.0.0/weights/yolov8n.pt"
print(f"Loading model from {weights_path}")
model = YOLO(weights_path)

# Run inference
results = model(frame_bgr, conf=0.3, classes=[0], verbose=True)

print(f"\n--- YOLO Results ---")
print(f"Number of results: {len(results)}")

if results and len(results) > 0:
    result = results[0]
    print(f"Boxes: {result.boxes}")
    if result.boxes is not None:
        print(f"Number of detections: {len(result.boxes)}")
        boxes = result.boxes.xyxy.cpu().numpy()
        confs = result.boxes.conf.cpu().numpy()
        classes = result.boxes.cls.cpu().numpy()

        for i, (box, conf, cls) in enumerate(zip(boxes, confs, classes)):
            print(f"  Detection {i}: class={cls}, conf={conf:.3f}, bbox={box}")
    else:
        print("No boxes in result")
else:
    print("No results from YOLO")

# Test with our inference module
print("\n--- Testing geo_fencing inference module ---")
from models.geo_fencing.v1_0_0.inference import infer

test_config = {
    "zones": [{
        "id": "zone_1",
        "name": "Test Zone",
        "points": [[648, 605], [877, 662], [842, 1024], [453, 900]],
        "type": "restricted"
    }]
}

result = infer(frame_bgr, config=test_config)
print(f"Result: {result}")
print(f"Violation detected: {result.get('violation_detected')}")
print(f"Detections: {result.get('detections')}")
print(f"Metadata: {result.get('metadata')}")
