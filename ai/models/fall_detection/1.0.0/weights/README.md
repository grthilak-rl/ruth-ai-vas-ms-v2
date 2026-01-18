# Weights directory
This directory should contain model weights for fall detection.

For MVP, weights loading is stubbed. Phase 2 will add:
- yolov7-w6-pose.pt (actual model weights)
- Or symlink to fall-detection-model/weights/

Model weights are large files and should NOT be committed to git.
Use .gitkeep to track the directory structure only.
