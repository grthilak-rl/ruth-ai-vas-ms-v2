# VAS-MS-V2 Integration Tests

Comprehensive integration test suite for validating VAS-MS-V2 API endpoints against a live VAS instance.

## Setup

### 1. Install Dependencies

```bash
cd tests
pip install -r requirements.txt
```

### 2. Configure Environment

Set environment variables for VAS connection:

```bash
export VAS_BASE_URL="http://10.30.250.245"
export VAS_DEFAULT_CLIENT_ID="vas-portal"
export VAS_DEFAULT_CLIENT_SECRET="vas-portal-secret-2024"
```

Or create a `.env` file in the tests directory:

```
VAS_BASE_URL=http://10.30.250.245
VAS_DEFAULT_CLIENT_ID=vas-portal
VAS_DEFAULT_CLIENT_SECRET=vas-portal-secret-2024
```

## Running Tests

### Run All Tests

```bash
python run_tests.py
```

Or using pytest directly:

```bash
pytest integration/ -v
```

### Run by Category

```bash
# Authentication tests only
python run_tests.py --auth

# Device management tests
python run_tests.py --device

# Stream management tests
python run_tests.py --stream

# WebRTC consumer tests
python run_tests.py --consumer

# Snapshot tests
python run_tests.py --snapshot

# Bookmark tests
python run_tests.py --bookmark

# HLS playback tests
python run_tests.py --hls
```

### Run Quick Tests (No Active Stream Required)

```bash
python run_tests.py --quick
```

### Run Tests Matching Pattern

```bash
python run_tests.py -k "test_authenticate"
python run_tests.py -k "snapshot and not delete"
```

### Generate HTML Report

```bash
python run_tests.py --report
```

### Stop on First Failure

```bash
python run_tests.py --failfast
```

## Test Structure

```
tests/
├── vas_client/              # VAS API client library
│   ├── __init__.py
│   ├── client.py           # VASClient class
│   └── models.py           # Pydantic models
├── integration/            # Integration tests
│   ├── test_01_authentication.py
│   ├── test_02_devices.py
│   ├── test_03_streams.py
│   ├── test_04_snapshots.py
│   ├── test_05_bookmarks.py
│   ├── test_06_consumers.py
│   └── test_07_hls.py
├── conftest.py             # Pytest fixtures
├── pytest.ini              # Pytest configuration
├── requirements.txt        # Python dependencies
├── run_tests.py           # Test runner script
└── README.md              # This file
```

## Test Categories

| Category | Marker | Description |
|----------|--------|-------------|
| Authentication | `@pytest.mark.auth` | Token generation, refresh, validation |
| Device | `@pytest.mark.device` | Device CRUD, RTSP validation |
| Stream | `@pytest.mark.stream` | Stream lifecycle, state machine |
| Consumer | `@pytest.mark.consumer` | WebRTC consumer attachment |
| Snapshot | `@pytest.mark.snapshot` | Snapshot creation, retrieval |
| Bookmark | `@pytest.mark.bookmark` | Bookmark creation, video clips |
| HLS | `@pytest.mark.hls` | HLS playlist, segments |
| Slow | `@pytest.mark.slow` | Tests that take >10 seconds |
| Requires Stream | `@pytest.mark.requires_stream` | Tests needing active stream |

## VAS Client Usage

The test suite includes a reusable VAS API client:

```python
from vas_client import VASClient

# Initialize client
client = VASClient(
    base_url="http://10.30.250.245",
    client_id="vas-portal",
    client_secret="vas-portal-secret-2024",
)

# Authenticate
token = client.authenticate()
print(f"Access token: {token.access_token}")

# List devices
devices = client.list_devices()
for device in devices:
    print(f"Device: {device.name} ({device.id})")

# Start stream
response = client.start_stream(device_id)
stream_id = response.v2_stream_id

# Wait for LIVE state
stream = client.wait_for_stream_live(stream_id)

# Create snapshot
snapshot = client.create_snapshot(stream_id, source="live")
snapshot = client.wait_for_snapshot_ready(snapshot.id)

# Download image
image_data = client.get_snapshot_image(snapshot.id)

# Create bookmark
bookmark = client.create_bookmark(
    stream_id=stream_id,
    label="Test Event",
    event_type="violation",
    before_seconds=5,
    after_seconds=10,
)
bookmark = client.wait_for_bookmark_ready(bookmark.id)

# Download video
video_data = client.get_bookmark_video(bookmark.id)

# Stop stream
client.stop_stream(device_id)
```

## Test Results

Tests produce output in the following format:

```
======================== VAS-MS-V2 INTEGRATION TEST SUMMARY ========================
Base URL: http://10.30.250.245
Client ID: vas-portal
================================================================================

tests/integration/test_01_authentication.py::TestAuthentication::test_authenticate_with_valid_credentials PASSED
tests/integration/test_01_authentication.py::TestAuthentication::test_token_refresh PASSED
...

==================== 45 passed, 3 skipped in 127.34s ====================
```

## Troubleshooting

### Connection Refused

```
VASError: [HTTP_ERROR] Connection refused
```

- Verify VAS_BASE_URL is correct
- Check if VAS service is running
- Ensure network connectivity to VAS server

### Authentication Failed

```
VASError: [401] INVALID_CREDENTIALS: Invalid client credentials
```

- Verify VAS_DEFAULT_CLIENT_ID and VAS_DEFAULT_CLIENT_SECRET
- Ensure credentials have appropriate scopes

### Stream Start Timeout

```
VASError: [504] STREAM_TIMEOUT: Stream did not reach LIVE state within 30s
```

- Check if test device has valid RTSP URL
- Verify camera is accessible from VAS server
- Increase timeout in test configuration

### No Test Device Available

```
SKIPPED: No test device available
```

- Ensure at least one device is configured in VAS
- Check device listing with `client.list_devices()`

## Contributing

When adding new tests:

1. Follow naming convention: `test_<category>_<feature>.py`
2. Use appropriate markers (`@pytest.mark.<category>`)
3. Use fixtures from `conftest.py` for common setup
4. Clean up resources in finally blocks
5. Document expected behavior in docstrings
