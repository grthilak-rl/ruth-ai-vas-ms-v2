# Ruth AI Unified Runtime - Tests

Integration and unit tests for the unified AI runtime.

## Running Tests

### Install Dependencies

```bash
cd /home/ruth-ai-vas-ms-v2
pip install pytest pytest-asyncio httpx
```

### Run All Tests

```bash
cd ai/tests
pytest -v
```

### Run Specific Test Files

```bash
# Frame decoding tests
pytest test_frame_decoding.py -v

# End-to-end inference tests
pytest test_inference_e2e.py -v
```

### Run Specific Tests

```bash
# Single test
pytest test_inference_e2e.py::test_health_endpoint -v

# Tests matching pattern
pytest -k "decode" -v
```

## Test Structure

### test_frame_decoding.py
Tests for base64 frame encoding/decoding functionality:
- JPEG and PNG format support
- BGR color format preservation
- Error handling for invalid inputs

### test_inference_e2e.py
End-to-end integration tests:
- Health and capabilities endpoints
- Inference endpoint with valid/invalid requests
- Response schema validation
- Error handling (missing models, invalid data)

### conftest.py
Pytest configuration and shared fixtures

## Expected Results

**Without model weights deployed:**
- All tests should pass
- Inference returns stub responses with `mode: "stub"` in metadata
- Response schemas are validated correctly

**With model weights deployed:**
- All tests should pass
- Inference returns actual detections with `mode: "inference"` in metadata
- Fall detection logic is exercised on test frames

## Test Coverage

Current test coverage includes:
- ✅ Base64 frame decoding (JPEG, PNG)
- ✅ Inference endpoint request validation
- ✅ Response schema compliance
- ✅ Error handling (404, 422, 500)
- ✅ Health and capabilities endpoints

Future test additions:
- Backend integration layer (frame fetcher, router)
- Model loading and sandbox creation
- Concurrent inference requests
- Performance benchmarks
