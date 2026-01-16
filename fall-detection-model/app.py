"""
Fall Detection Model Service
FastAPI application for fall detection using pose estimation
"""

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import cv2
import numpy as np
from pathlib import Path
import logging
import os

from detector import FallDetector

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Fall Detection Model Service",
    description="AI model service for detecting falls using pose estimation",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global model instance
detector = None

def load_model():
    """Load the fall detection model on startup"""
    global detector

    # Try multiple paths: Docker path first, then local path
    possible_paths = [
        Path("/app/weights/yolov7-w6-pose.pt"),  # Docker path
        Path(__file__).parent / "weights" / "yolov7-w6-pose.pt",  # Local path
    ]

    model_path = None
    for path in possible_paths:
        if path.exists():
            model_path = path
            break

    # Check if model exists, if not, use placeholder
    if model_path is None:
        logger.warning(f"Model weights not found in any of: {possible_paths}")
        logger.warning("Fall detection will run in placeholder mode")
        return None

    try:
        detector = FallDetector(str(model_path))
        logger.info(f"Loaded fall detection model from {model_path}")
        return detector
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        return None

@app.on_event("startup")
async def startup_event():
    """Initialize model when the API starts"""
    logger.info("Starting Fall Detection Model Service...")
    load_model()
    logger.info("Fall Detection Model Service ready")

def process_uploaded_image(file_content: bytes) -> np.ndarray:
    """Convert uploaded file to OpenCV image"""
    nparr = np.frombuffer(file_content, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Invalid image format")
    return image

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Fall Detection Model",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "fall-detection-model",
        "version": "1.0.0",
        "model_loaded": detector is not None
    }

@app.get("/info")
async def model_info():
    """Get model information and metadata"""
    return {
        "id": "fall-detection",
        "name": "Fall Detection",
        "description": "Detects falls using human pose estimation and keypoint analysis",
        "version": "1.0.0",
        "type": "pose_estimation",
        "input_format": "image",
        "accuracy": 0.85,
        "status": "loaded" if detector is not None else "not_loaded",
        "capabilities": [
            "fall_detection",
            "pose_estimation",
            "keypoint_analysis"
        ],
        "supported_formats": ["jpg", "jpeg", "png"]
    }

@app.post("/detect")
async def detect_fall(file: UploadFile = File(...)):
    """
    Detect falls in an uploaded image

    Args:
        file: Uploaded image file

    Returns:
        Detection results including violation status and confidence
    """
    if detector is None:
        # Return mock detection response for testing (model weights not loaded)
        logger.info("Returning mock detection response - model weights not loaded")
        return {
            "success": True,
            "model": "fall-detection",
            "status": "mock_mode",
            "violation_detected": False,
            "confidence": 0.0,
            "detections": [
                {
                    "bbox": [100, 100, 300, 500],  # x1, y1, x2, y2 in 640x640 coordinates
                    "confidence": 0.85,
                    "keypoints": [
                        {"x": 200, "y": 120, "confidence": 0.9},  # nose
                        {"x": 190, "y": 115, "confidence": 0.85}, # left_eye
                        {"x": 210, "y": 115, "confidence": 0.85}, # right_eye
                        {"x": 185, "y": 120, "confidence": 0.8},  # left_ear
                        {"x": 215, "y": 120, "confidence": 0.8},  # right_ear
                        {"x": 170, "y": 180, "confidence": 0.9},  # left_shoulder
                        {"x": 230, "y": 180, "confidence": 0.9},  # right_shoulder
                        {"x": 160, "y": 250, "confidence": 0.85}, # left_elbow
                        {"x": 240, "y": 250, "confidence": 0.85}, # right_elbow
                        {"x": 150, "y": 320, "confidence": 0.8},  # left_wrist
                        {"x": 250, "y": 320, "confidence": 0.8},  # right_wrist
                        {"x": 180, "y": 320, "confidence": 0.9},  # left_hip
                        {"x": 220, "y": 320, "confidence": 0.9},  # right_hip
                        {"x": 180, "y": 420, "confidence": 0.85}, # left_knee
                        {"x": 220, "y": 420, "confidence": 0.85}, # right_knee
                        {"x": 180, "y": 500, "confidence": 0.8},  # left_ankle
                        {"x": 220, "y": 500, "confidence": 0.8}   # right_ankle
                    ]
                }
            ],
            "detection_count": 1,
            "model_name": "fall_detector",
            "model_version": "1.0.0"
        }

    try:
        # Process uploaded image
        file_content = await file.read()
        image = process_uploaded_image(file_content)

        # Run detection
        result = detector.detect(image)

        return {
            "success": True,
            "model": "fall-detection",
            **result
        }

    except Exception as e:
        logger.error(f"Fall detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=os.getenv("ENVIRONMENT") == "development"
    )
