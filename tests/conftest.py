"""
Pytest configuration and fixtures for VAS-MS-V2 integration tests
"""

import os
import pytest
from datetime import datetime
from typing import Generator, Optional
from vas_client import VASClient

# Test configuration from environment
VAS_BASE_URL = os.getenv("VAS_BASE_URL", "http://10.30.250.245:8085")
VAS_CLIENT_ID = os.getenv("VAS_DEFAULT_CLIENT_ID", "vas-portal")
VAS_CLIENT_SECRET = os.getenv("VAS_DEFAULT_CLIENT_SECRET", "vas-portal-secret-2024")


def pytest_configure(config):
    """Configure custom markers"""
    config.addinivalue_line("markers", "auth: Authentication tests")
    config.addinivalue_line("markers", "device: Device management tests")
    config.addinivalue_line("markers", "stream: Stream management tests")
    config.addinivalue_line("markers", "consumer: WebRTC consumer tests")
    config.addinivalue_line("markers", "snapshot: Snapshot tests")
    config.addinivalue_line("markers", "bookmark: Bookmark tests")
    config.addinivalue_line("markers", "hls: HLS playback tests")
    config.addinivalue_line("markers", "slow: Slow tests (>10s)")
    config.addinivalue_line("markers", "requires_stream: Tests requiring an active stream")


@pytest.fixture(scope="session")
def vas_client() -> Generator[VASClient, None, None]:
    """
    Session-scoped VAS client fixture.
    Authenticates once and reuses token across tests.
    """
    client = VASClient(
        base_url=VAS_BASE_URL,
        client_id=VAS_CLIENT_ID,
        client_secret=VAS_CLIENT_SECRET,
    )
    yield client
    # Cleanup not strictly needed for httpx.Client but good practice


@pytest.fixture(scope="function")
def authenticated_client(vas_client: VASClient) -> VASClient:
    """
    Function-scoped fixture that ensures client is authenticated.
    """
    vas_client.ensure_authenticated()
    return vas_client


@pytest.fixture(scope="session")
def test_device_id(vas_client: VASClient) -> Optional[str]:
    """
    Get an existing device ID for testing.
    Returns None if no devices available.
    """
    vas_client.ensure_authenticated()
    try:
        devices = vas_client.list_devices(limit=1)
        if devices:
            return devices[0].id
    except Exception:
        pass
    return None


@pytest.fixture(scope="module")
def active_stream(vas_client: VASClient, test_device_id: Optional[str]):
    """
    Module-scoped fixture that starts a stream and yields stream info.
    Stops the stream after all tests in module complete.
    """
    if not test_device_id:
        pytest.skip("No test device available")

    vas_client.ensure_authenticated()

    # Start stream
    start_response = vas_client.start_stream(test_device_id)
    stream_id = start_response.v2_stream_id

    # Wait for LIVE state
    try:
        stream = vas_client.wait_for_stream_live(stream_id, timeout=30.0)
        yield {
            "device_id": test_device_id,
            "stream_id": stream_id,
            "stream": stream,
            "start_response": start_response,
        }
    finally:
        # Cleanup: stop stream
        try:
            vas_client.stop_stream(test_device_id)
        except Exception:
            pass


@pytest.fixture
def stream_id(active_stream) -> str:
    """Convenience fixture to get just the stream ID"""
    return active_stream["stream_id"]


@pytest.fixture
def device_id(active_stream) -> str:
    """Convenience fixture to get just the device ID"""
    return active_stream["device_id"]


# Test result tracking
class TestResults:
    """Track test results for reporting"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []
        self.start_time = datetime.now()

    def record_pass(self, test_name: str):
        self.passed += 1

    def record_fail(self, test_name: str, error: str):
        self.failed += 1
        self.errors.append({"test": test_name, "error": error})

    def record_skip(self, test_name: str, reason: str):
        self.skipped += 1

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped

    @property
    def duration(self) -> float:
        return (datetime.now() - self.start_time).total_seconds()


@pytest.fixture(scope="session")
def test_results() -> TestResults:
    """Session-scoped test results tracker"""
    return TestResults()


# Hooks for better reporting
def pytest_runtest_makereport(item, call):
    """Custom report generation"""
    if call.when == "call":
        if call.excinfo is not None:
            # Test failed
            error_msg = str(call.excinfo.value)
            print(f"\n  FAILED: {item.name}")
            print(f"    Error: {error_msg[:200]}")
        else:
            print(f"\n  PASSED: {item.name}")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print custom summary"""
    print("\n" + "=" * 60)
    print("VAS-MS-V2 INTEGRATION TEST SUMMARY")
    print("=" * 60)
    print(f"Base URL: {VAS_BASE_URL}")
    print(f"Client ID: {VAS_CLIENT_ID}")
    print("=" * 60)
