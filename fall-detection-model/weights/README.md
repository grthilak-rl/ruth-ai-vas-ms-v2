# Fall Detection Model Weights

## Required Model File

Place the YOLOv7 pose estimation model weights in this directory:

- **Filename**: `yolov7-w6-pose.pt`
- **Model**: YOLOv7-W6 Pose Estimation
- **Download**: https://github.com/WongKinYiu/yolov7/releases

## Installation

```bash
cd /home/atgin-rnd-ubuntu/ruth-ai-monitor/services/fall-detection-model/weights
wget https://github.com/WongKinYiu/yolov7/releases/download/v0.1/yolov7-w6-pose.pt
```

## Note

Without this model file, the fall detection service will run in placeholder mode and return mock responses.
