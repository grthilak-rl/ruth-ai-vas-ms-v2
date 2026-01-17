"""
PPE Detection Model Service
FastAPI application for detecting Personal Protective Equipment (PPE)
using multiple specialized YOLOv8 models
"""

from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Set
import uvicorn
import cv2
import numpy as np
from pathlib import Path
import logging
import os
import time
from enum import Enum

from detector import PPEDetector, DetectionMode

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PPE Detection Model Service",
    description="AI model service for detecting Personal Protective Equipment (PPE) using multiple YOLOv8 models",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class DetectionModeEnum(str, Enum):
    presence = "presence"
    violation = "violation"
    full = "full"


class ThresholdUpdate(BaseModel):
    model_name: str = Field(..., description="Name of the model to update")
    threshold: float = Field(..., ge=0.0, le=1.0, description="New confidence threshold")


class BatchDetectionRequest(BaseModel):
    mode: DetectionModeEnum = Field(default=DetectionModeEnum.full, description="Detection mode")
    confidence_threshold: Optional[float] = Field(None, ge=0.0, le=1.0, description="Override confidence threshold")
    models: Optional[List[str]] = Field(None, description="Specific models to run")


# Global detector instance
detector: Optional[PPEDetector] = None


def get_weights_dir() -> Path:
    """Get the weights directory path"""
    # Try multiple paths: Docker path first, then local path
    possible_paths = [
        Path("/app/weights"),  # Docker path
        Path(__file__).parent / "weights",  # Local path
    ]

    for path in possible_paths:
        if path.exists() and (path / "both_classes").exists():
            return path

    # Return default path even if it doesn't exist (for mock mode)
    return Path(__file__).parent / "weights"


def load_detector() -> Optional[PPEDetector]:
    """Load the PPE detector with all available models"""
    global detector

    weights_dir = get_weights_dir()

    # Check if weights exist
    if not weights_dir.exists():
        logger.warning(f"Weights directory not found: {weights_dir}")
        logger.warning("PPE detection will run in placeholder/mock mode")
        return None

    both_classes = weights_dir / "both_classes"
    no_classes = weights_dir / "no_classes"

    if not both_classes.exists() and not no_classes.exists():
        logger.warning("No model weight directories found")
        logger.warning("PPE detection will run in placeholder/mock mode")
        return None

    # Check for any .pt files
    pt_files = list(both_classes.glob("*.pt")) + list(no_classes.glob("*.pt")) if both_classes.exists() and no_classes.exists() else []

    if len(pt_files) == 0:
        # Check individual directories
        pt_files = []
        if both_classes.exists():
            pt_files.extend(both_classes.glob("*.pt"))
        if no_classes.exists():
            pt_files.extend(no_classes.glob("*.pt"))

    if len(list(pt_files)) == 0:
        logger.warning("No .pt weight files found in weights directory")
        logger.warning("PPE detection will run in placeholder/mock mode")
        return None

    try:
        # Get device from environment or auto-detect
        device = os.getenv("AI_DEVICE", "auto")

        # Get global confidence threshold from environment
        global_threshold = float(os.getenv("PPE_CONFIDENCE_THRESHOLD", "0.5"))

        detector = PPEDetector(
            weights_dir=str(weights_dir),
            device=device,
            global_confidence_threshold=global_threshold
        )

        logger.info(f"Loaded PPE detector from {weights_dir}")
        return detector

    except Exception as e:
        logger.error(f"Failed to load PPE detector: {e}")
        return None


@app.on_event("startup")
async def startup_event():
    """Initialize detector when the API starts"""
    logger.info("Starting PPE Detection Model Service...")
    load_detector()
    if detector is not None:
        status = detector.get_model_status()
        logger.info(f"PPE Detection Model Service ready with {status['total_models_loaded']} models")
    else:
        logger.info("PPE Detection Model Service ready (mock mode)")


def process_uploaded_image(file_content: bytes) -> np.ndarray:
    """Convert uploaded file to OpenCV image"""
    nparr = np.frombuffer(file_content, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Invalid image format")
    return image


def get_mock_detection_response(mode: str = "full") -> dict:
    """Return mock detection response for testing when models are not loaded"""
    return {
        "success": True,
        "model": "ppe-detection",
        "status": "mock_mode",
        "violation_detected": True,
        "violation_type": "ppe_violation",
        "severity": "medium",
        "confidence": 0.78,
        "detections": [
            {
                "item": "person",
                "status": "present",
                "confidence": 0.92,
                "bbox": [100.0, 50.0, 350.0, 480.0],
                "class_id": 0,
                "class_name": "person",
                "model_source": "person"
            },
            {
                "item": "hardhat",
                "status": "present",
                "confidence": 0.87,
                "bbox": [180.0, 55.0, 270.0, 120.0],
                "class_id": 0,
                "class_name": "hardhat",
                "model_source": "hardhat"
            },
            {
                "item": "vest",
                "status": "present",
                "confidence": 0.91,
                "bbox": [120.0, 140.0, 330.0, 350.0],
                "class_id": 0,
                "class_name": "vest",
                "model_source": "vest"
            },
            {
                "item": "goggles",
                "status": "missing",
                "confidence": 0.72,
                "bbox": [150.0, 60.0, 300.0, 200.0],
                "class_id": 0,
                "class_name": "no_goggles",
                "model_source": "no_goggles"
            }
        ],
        "persons_detected": 1,
        "violations": ["goggles"],
        "ppe_present": ["hardhat", "vest"],
        "detection_count": 4,
        "model_name": "ppe_detector",
        "model_version": "1.0.0",
        "mode": mode,
        "inference_time_ms": 45.32,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "PPE Detection Model",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    model_loaded = detector is not None
    model_count = 0

    if model_loaded:
        status = detector.get_model_status()
        model_count = status["total_models_loaded"]

    return {
        "status": "healthy",
        "service": "ppe-detection-model",
        "version": "1.0.0",
        "model_loaded": model_loaded,
        "models_count": model_count,
        "device": detector.device if detector else "N/A"
    }


@app.get("/info")
async def model_info():
    """Get model information and metadata"""
    model_loaded = detector is not None

    supported_items = {
        "presence_detection": ["hardhat", "vest", "goggles", "gloves", "boots", "person"],
        "violation_detection": ["hardhat", "vest", "goggles", "gloves", "boots", "mask"]
    }

    if model_loaded:
        supported_items = detector.get_supported_items()
        model_status = detector.get_model_status()
    else:
        model_status = {"total_models_loaded": 0}

    return {
        "id": "ppe-detection",
        "name": "PPE Detection",
        "description": "Detects Personal Protective Equipment presence and violations using multiple YOLOv8 models",
        "version": "1.0.0",
        "type": "object_detection",
        "input_format": "image",
        "accuracy": 0.87,
        "status": "loaded" if model_loaded else "not_loaded",
        "capabilities": [
            "ppe_presence_detection",
            "ppe_violation_detection",
            "multi_item_detection",
            "batch_inference"
        ],
        "supported_formats": ["jpg", "jpeg", "png", "bmp"],
        "detection_modes": ["presence", "violation", "full"],
        "supported_items": supported_items,
        "models_loaded": model_status.get("total_models_loaded", 0),
        "hardware": {
            "device": detector.device if detector else "N/A",
            "gpu_available": "cuda" in (detector.device if detector else "")
        }
    }


@app.get("/models")
async def get_models():
    """Get detailed status of all loaded models"""
    if detector is None:
        return {
            "status": "not_loaded",
            "message": "PPE detection models are not loaded",
            "presence_models": {},
            "violation_models": {},
            "total_models_loaded": 0
        }

    return detector.get_model_status()


@app.post("/detect")
async def detect_ppe(
    file: UploadFile = File(...),
    mode: DetectionModeEnum = Query(default=DetectionModeEnum.full, description="Detection mode"),
    confidence: Optional[float] = Query(default=None, ge=0.0, le=1.0, description="Override confidence threshold")
):
    """
    Detect PPE in an uploaded image

    Args:
        file: Uploaded image file
        mode: Detection mode (presence, violation, or full)
        confidence: Optional override for confidence threshold

    Returns:
        Detection results including violations and present PPE items
    """
    if detector is None:
        # Return mock detection response for testing (model weights not loaded)
        logger.info("Returning mock detection response - model weights not loaded")
        return get_mock_detection_response(mode.value)

    try:
        # Process uploaded image
        file_content = await file.read()
        image = process_uploaded_image(file_content)

        # Convert mode enum to DetectionMode
        detection_mode = DetectionMode(mode.value)

        # Run detection
        result = detector.detect(
            image,
            mode=detection_mode,
            confidence_override=confidence
        )

        return {
            "success": True,
            "model": "ppe-detection",
            **result
        }

    except Exception as e:
        logger.error(f"PPE detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/detect/batch")
async def detect_ppe_batch(
    files: List[UploadFile] = File(...),
    mode: DetectionModeEnum = Query(default=DetectionModeEnum.full, description="Detection mode"),
    confidence: Optional[float] = Query(default=None, ge=0.0, le=1.0, description="Override confidence threshold")
):
    """
    Detect PPE in multiple uploaded images

    Args:
        files: List of uploaded image files
        mode: Detection mode (presence, violation, or full)
        confidence: Optional override for confidence threshold

    Returns:
        List of detection results for each image
    """
    if detector is None:
        # Return mock responses for testing
        logger.info("Returning mock batch detection response - model weights not loaded")
        return {
            "success": True,
            "model": "ppe-detection",
            "status": "mock_mode",
            "results": [get_mock_detection_response(mode.value) for _ in files],
            "total_images": len(files)
        }

    try:
        results = []
        for file in files:
            file_content = await file.read()
            image = process_uploaded_image(file_content)

            detection_mode = DetectionMode(mode.value)
            result = detector.detect(
                image,
                mode=detection_mode,
                confidence_override=confidence
            )
            results.append(result)

        return {
            "success": True,
            "model": "ppe-detection",
            "results": results,
            "total_images": len(files)
        }

    except Exception as e:
        logger.error(f"Batch PPE detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/threshold")
async def update_threshold(request: ThresholdUpdate):
    """
    Update confidence threshold for a specific model

    Args:
        request: Threshold update request with model name and new threshold
    """
    if detector is None:
        raise HTTPException(status_code=503, detail="PPE detection models are not loaded")

    try:
        detector.update_threshold(request.model_name, request.threshold)
        return {
            "success": True,
            "message": f"Updated threshold for {request.model_name} to {request.threshold}"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/thresholds")
async def get_thresholds():
    """Get current confidence thresholds for all models"""
    if detector is None:
        return {
            "status": "not_loaded",
            "thresholds": detector.DEFAULT_THRESHOLDS if hasattr(detector, 'DEFAULT_THRESHOLDS') else {}
        }

    return {
        "status": "loaded",
        "thresholds": {
            name: config.confidence_threshold
            for name, config in detector.model_configs.items()
        }
    }


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8001,
        reload=os.getenv("ENVIRONMENT") == "development"
    )
