"""
Test base64 frame decoding functionality
"""

import base64
import io
import numpy as np
import pytest
from PIL import Image

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ai.server.routes.inference import _decode_base64_frame


def create_test_image(width=640, height=480, color=(255, 0, 0)):
    """Create a test image in BGR format."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = color  # Fill with color (BGR)
    return img


def encode_image_to_base64(img_array, format="jpeg"):
    """Encode numpy array to base64 string."""
    # Convert BGR to RGB for PIL
    img_rgb = img_array[:, :, ::-1]
    img_pil = Image.fromarray(img_rgb)

    buffer = io.BytesIO()
    img_pil.save(buffer, format=format.upper())
    img_bytes = buffer.getvalue()

    return base64.b64encode(img_bytes).decode('utf-8')


def test_decode_jpeg_frame():
    """Test decoding JPEG-encoded base64 frame."""
    # Create test image
    test_img = create_test_image(640, 480, color=(100, 150, 200))

    # Encode to base64
    base64_str = encode_image_to_base64(test_img, format="jpeg")

    # Decode
    decoded = _decode_base64_frame(base64_str, format="jpeg")

    # Verify
    assert isinstance(decoded, np.ndarray)
    assert decoded.shape == (480, 640, 3)
    assert decoded.dtype == np.uint8


def test_decode_png_frame():
    """Test decoding PNG-encoded base64 frame."""
    # Create test image
    test_img = create_test_image(320, 240, color=(50, 100, 150))

    # Encode to base64
    base64_str = encode_image_to_base64(test_img, format="png")

    # Decode
    decoded = _decode_base64_frame(base64_str, format="png")

    # Verify
    assert isinstance(decoded, np.ndarray)
    assert decoded.shape == (240, 320, 3)
    assert decoded.dtype == np.uint8


def test_decode_preserves_bgr_format():
    """Test that decoded image is in BGR format (OpenCV convention)."""
    # Create red image in BGR (0, 0, 255)
    test_img = create_test_image(100, 100, color=(0, 0, 255))

    # Encode and decode
    base64_str = encode_image_to_base64(test_img, format="jpeg")
    decoded = _decode_base64_frame(base64_str, format="jpeg")

    # Check that blue channel (index 0) is dominant
    # JPEG compression may cause slight variations
    assert decoded[50, 50, 2] > 200  # Red channel should be high
    assert decoded[50, 50, 0] < 50   # Blue channel should be low


def test_decode_invalid_base64():
    """Test that invalid base64 raises ValueError."""
    with pytest.raises(ValueError, match="Failed to decode base64"):
        _decode_base64_frame("invalid_base64_string", format="jpeg")


def test_decode_empty_string():
    """Test that empty string raises ValueError."""
    with pytest.raises(ValueError, match="Failed to decode base64"):
        _decode_base64_frame("", format="jpeg")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
