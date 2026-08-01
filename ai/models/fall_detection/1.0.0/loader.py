"""
Fall Detection Model Loader

Loads the YOLOv7-Pose model for fall detection.
This file is called by the runtime to load the model instance.
"""

from pathlib import Path
from typing import Any
import sys
import logging

logger = logging.getLogger(__name__)


def load(weights_path: Path, device: str = "cpu") -> Any:
    """
    Load the YOLOv7-Pose model from weights.

    Args:
        weights_path: Path to the weights directory
        device: Torch device to load onto ("cpu", "cuda:0", ...). The runtime
            passes the device it allocated via GPUManager; declaring this
            parameter is what opts the model into that allocation at all
            (ModelLoader inspects the signature and falls back to a CPU-only
            call when `device` is absent).

    Returns:
        Loaded model instance ready for inference
    """
    # Add lib directory to path for model imports
    model_dir = weights_path.parent
    lib_dir = model_dir / "lib"

    if str(lib_dir) not in sys.path:
        sys.path.insert(0, str(lib_dir))

    # Import after adding to path
    from models.experimental import attempt_load

    # Find the weights file
    weights_file = weights_path / "yolov7-w6-pose.pt"

    if not weights_file.exists():
        raise FileNotFoundError(f"Model weights not found: {weights_file}")

    logger.info(f"Loading YOLOv7-Pose model from {weights_file} on {device}")

    # Load straight onto the allocated device. Loading to CPU and relying on
    # "the runtime can move it later" never happened — nothing moved it, so
    # every inference ran on CPU (~559ms) despite an available GPU.
    model = attempt_load(str(weights_file), map_location=device)
    model.eval()

    logger.info(f"Successfully loaded fall detection model on {device}")

    return model
