# Model Weights

This repository does not include the trained model weight files
(.pt files) due to their size (~837 MB total). To run real
inference, weights must be placed on disk before starting the
unified AI runtime container.

## Required files

| File | Size | Path |
|------|------|------|
| yolov8n.pt | 6.3 MB | ai/yolov8n.pt |
| yolov7-w6-pose.pt | 307 MB | ai/models/fall_detection/1.0.0/weights/yolov7-w6-pose.pt |
| yolov8n.pt | 6.3 MB | ai/models/geo_fencing/1.0.0/weights/yolov8n.pt |
| person.pt | 50 MB | ai/models/geo_fencing/1.0.0/weights/person.pt |
| hardhat.pt | 6.1 MB | ai/models/ppe_detection/1.0.0/weights/both_classes/hardhat.pt |
| vest.pt | 50 MB | ai/models/ppe_detection/1.0.0/weights/both_classes/vest.pt |
| gloves.pt | 6.1 MB | ai/models/ppe_detection/1.0.0/weights/both_classes/gloves.pt |
| goggles.pt | 50 MB | ai/models/ppe_detection/1.0.0/weights/both_classes/goggles.pt |
| boots.pt | 50 MB | ai/models/ppe_detection/1.0.0/weights/both_classes/boots.pt |
| person.pt | 50 MB | ai/models/ppe_detection/1.0.0/weights/both_classes/person.pt |
| no_hardhat.pt | 50 MB | ai/models/ppe_detection/1.0.0/weights/no_classes/no_hardhat.pt |
| no_vest.pt | 50 MB | ai/models/ppe_detection/1.0.0/weights/no_classes/no_vest.pt |
| no_gloves.pt | 50 MB | ai/models/ppe_detection/1.0.0/weights/no_classes/no_gloves.pt |
| no_goggles.pt | 50 MB | ai/models/ppe_detection/1.0.0/weights/no_classes/no_goggles.pt |
| no_boots.pt | 50 MB | ai/models/ppe_detection/1.0.0/weights/no_classes/no_boots.pt |
| no_mask.pt | 6.0 MB | ai/models/ppe_detection/1.0.0/weights/no_classes/no_mask.pt |

Total: ~837 MB across 16 files.

## How to obtain

Copy from an existing running deployment via rsync or scp.
Example, pulling from a deployment at HOST:

    rsync -av --progress \
      user@HOST:/home/project/ruth-ai-vas-ms-v2/ai/yolov8n.pt \
      ai/

    rsync -av --progress \
      user@HOST:/home/project/ruth-ai-vas-ms-v2/ai/models/ \
      ai/models/

After copying, verify all 16 files are in place:

    find ai -name "*.pt" -exec ls -lh {} \;

## What happens without weights

Without weights, models fall back to stub mode and return
detection_count=0 for every frame. The pipeline plumbing works
(frame fetch, runtime call, response, DB writes) but no real
detections fire. The unified runtime logs "Failed to load model"
warnings.

## Models that do not need weights

`tank_overflow_monitoring` uses classical CV (OpenCV edge detection)
and requires no weight files. It will work end-to-end with no
weights present.
