"""
End-to-end integration tests for unified runtime inference
"""

import base64
import io
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import the FastAPI app
from ai.server.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def create_test_frame_base64(width=640, height=480):
    """Create a test frame encoded as base64."""
    # Create random test image
    img = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)

    # Convert to PIL and encode
    img_rgb = img[:, :, ::-1]  # BGR to RGB
    img_pil = Image.fromarray(img_rgb)

    buffer = io.BytesIO()
    img_pil.save(buffer, format="JPEG")
    img_bytes = buffer.getvalue()

    return base64.b64encode(img_bytes).decode('utf-8')


def test_health_endpoint(client):
    """Test that health endpoint returns 200."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] in ["healthy", "degraded"]


def test_capabilities_endpoint(client):
    """Test that capabilities endpoint returns model info."""
    response = client.get("/capabilities")
    assert response.status_code == 200

    data = response.json()
    assert "models" in data
    assert isinstance(data["models"], list)


def test_inference_endpoint_with_valid_request(client):
    """Test inference endpoint with valid request."""
    # Create test frame
    frame_base64 = create_test_frame_base64()

    # Create inference request
    request_payload = {
        "stream_id": "550e8400-e29b-41d4-a716-446655440000",
        "device_id": "660e8400-e29b-41d4-a716-446655440001",
        "frame_base64": frame_base64,
        "frame_format": "jpeg",
        "frame_width": 640,
        "frame_height": 480,
        "timestamp": "2026-01-18T12:00:00Z",
        "model_id": "fall_detection",
        "model_version": "1.0.0",
        "priority": 5,
        "metadata": {}
    }

    # Send request
    response = client.post("/inference", json=request_payload)

    # Verify response
    assert response.status_code == 200

    data = response.json()
    assert "request_id" in data
    assert "status" in data
    assert "model_id" in data
    assert "model_version" in data
    assert "inference_time_ms" in data
    assert "result" in data

    # Verify result structure
    result = data["result"]
    assert "violation_detected" in result
    assert "severity" in result
    assert "confidence" in result
    assert "detections" in result
    assert "detection_count" in result


def test_inference_endpoint_missing_frame():
    """Test that missing frame_base64 returns 422."""
    client = TestClient(app)

    request_payload = {
        "stream_id": "550e8400-e29b-41d4-a716-446655440000",
        "timestamp": "2026-01-18T12:00:00Z",
        "model_id": "fall_detection"
        # Missing frame_base64
    }

    response = client.post("/inference", json=request_payload)
    assert response.status_code == 422  # Validation error


def test_inference_endpoint_invalid_model():
    """Test that requesting non-existent model returns 404."""
    client = TestClient(app)

    frame_base64 = create_test_frame_base64()

    request_payload = {
        "stream_id": "550e8400-e29b-41d4-a716-446655440000",
        "frame_base64": frame_base64,
        "frame_format": "jpeg",
        "timestamp": "2026-01-18T12:00:00Z",
        "model_id": "non_existent_model"
    }

    response = client.post("/inference", json=request_payload)
    assert response.status_code == 404


def test_inference_response_schema(client):
    """Test that inference response matches expected schema."""
    frame_base64 = create_test_frame_base64()

    request_payload = {
        "stream_id": "550e8400-e29b-41d4-a716-446655440000",
        "frame_base64": frame_base64,
        "frame_format": "jpeg",
        "timestamp": "2026-01-18T12:00:00Z",
        "model_id": "fall_detection"
    }

    response = client.post("/inference", json=request_payload)
    assert response.status_code == 200

    data = response.json()

    # Top-level fields
    assert isinstance(data["request_id"], str)
    assert data["status"] in ["success", "failed"]
    assert data["model_id"] == "fall_detection"
    assert isinstance(data["model_version"], str)
    assert isinstance(data["inference_time_ms"], (int, float))
    assert data["inference_time_ms"] >= 0

    # Result fields (when status is success)
    if data["status"] == "success":
        result = data["result"]
        assert isinstance(result["violation_detected"], bool)
        assert result["severity"] in ["low", "medium", "high", "critical"]
        assert isinstance(result["confidence"], (int, float))
        assert 0.0 <= result["confidence"] <= 1.0
        assert isinstance(result["detections"], list)
        assert isinstance(result["detection_count"], int)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
