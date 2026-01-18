"""
Ruth AI Unified Runtime - Locust Load Tests

HTTP load testing scenarios using Locust.

Run tests:
    # Install locust
    pip install locust

    # Run baseline test (1 user)
    locust -f locustfile.py --host=http://localhost:8000 --users=1 --spawn-rate=1 --run-time=60s --headless

    # Run ramp-up test (1→20 users over 120s)
    locust -f locustfile.py --host=http://localhost:8000 --users=20 --spawn-rate=1 --run-time=300s --headless

    # Run sustained load (20 users, 5 minutes)
    locust -f locustfile.py --host=http://localhost:8000 --users=20 --spawn-rate=5 --run-time=300s --headless

    # Run burst test (50 users)
    locust -f locustfile.py --host=http://localhost:8000 --users=50 --spawn-rate=10 --run-time=120s --headless

Performance Targets:
    - p50 latency: < 100ms
    - p99 latency: < 500ms
    - Error rate: < 1%
    - No memory leaks over 5 minute test
"""

import base64
import io
import random
from datetime import datetime

import numpy as np
from locust import HttpUser, task, between, events
from PIL import Image


def create_test_frame_base64(width=640, height=480):
    """
    Create a test frame encoded as base64.

    Args:
        width: Frame width
        height: Frame height

    Returns:
        Base64-encoded JPEG string
    """
    # Create random test image
    img = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)

    # Convert to PIL and encode
    img_rgb = img[:, :, ::-1]  # BGR to RGB
    img_pil = Image.fromarray(img_rgb)

    buffer = io.BytesIO()
    img_pil.save(buffer, format="JPEG", quality=85)
    img_bytes = buffer.getvalue()

    return base64.b64encode(img_bytes).decode('utf-8')


class InferenceUser(HttpUser):
    """
    Simulated user performing inference requests.

    Behavior:
    - Sends inference requests with base64-encoded frames
    - Random wait time between requests (1-3 seconds)
    - Tests fall_detection model
    """

    wait_time = between(1, 3)  # Wait 1-3 seconds between requests

    def on_start(self):
        """Initialize user session."""
        # Pre-generate test frames for reuse
        self.test_frames = [
            create_test_frame_base64(width=640, height=480)
            for _ in range(10)  # 10 different frames
        ]

    @task(10)  # Weight: 10 (most common task)
    def submit_inference(self):
        """Submit inference request."""
        # Select random frame
        frame_base64 = random.choice(self.test_frames)

        # Create request
        payload = {
            "stream_id": "550e8400-e29b-41d4-a716-446655440000",
            "device_id": "660e8400-e29b-41d4-a716-446655440001",
            "frame_base64": frame_base64,
            "frame_format": "jpeg",
            "frame_width": 640,
            "frame_height": 480,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "model_id": "fall_detection",
            "priority": 5,
            "metadata": {}
        }

        # Send request
        with self.client.post(
            "/inference",
            json=payload,
            catch_response=True,
            name="POST /inference (fall_detection)"
        ) as response:
            if response.status_code == 200:
                data = response.json()

                # Validate response structure
                if "request_id" not in data or "status" not in data:
                    response.failure(f"Invalid response structure: {data}")
                elif data["status"] != "success":
                    response.failure(f"Inference failed: {data.get('error', 'unknown')}")
                else:
                    response.success()
            else:
                response.failure(f"HTTP {response.status_code}: {response.text}")

    @task(2)  # Weight: 2 (occasional)
    def check_health(self):
        """Check health endpoint."""
        with self.client.get(
            "/health",
            catch_response=True,
            name="GET /health"
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if "status" in data and data["status"] in ["healthy", "degraded"]:
                    response.success()
                else:
                    response.failure(f"Unhealthy status: {data.get('status')}")
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(1)  # Weight: 1 (rare)
    def check_capabilities(self):
        """Check capabilities endpoint."""
        with self.client.get(
            "/capabilities",
            catch_response=True,
            name="GET /capabilities"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")


class MultiModelUser(HttpUser):
    """
    Simulated user testing multiple models.

    Splits traffic across fall_detection and helmet_detection.
    """

    wait_time = between(1, 2)

    def on_start(self):
        """Initialize user session."""
        self.test_frames = [
            create_test_frame_base64(width=640, height=480)
            for _ in range(5)
        ]

    @task(5)
    def submit_fall_detection(self):
        """Submit fall detection inference."""
        frame_base64 = random.choice(self.test_frames)

        payload = {
            "stream_id": "550e8400-e29b-41d4-a716-446655440000",
            "frame_base64": frame_base64,
            "frame_format": "jpeg",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "model_id": "fall_detection",
            "metadata": {}
        }

        with self.client.post("/inference", json=payload, catch_response=True, name="POST /inference (fall_detection)") as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(5)
    def submit_helmet_detection(self):
        """Submit helmet detection inference."""
        frame_base64 = random.choice(self.test_frames)

        payload = {
            "stream_id": "550e8400-e29b-41d4-a716-446655440001",
            "frame_base64": frame_base64,
            "frame_format": "jpeg",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "model_id": "helmet_detection",
            "metadata": {}
        }

        # Expect 404 if helmet_detection not loaded
        with self.client.post("/inference", json=payload, catch_response=True, name="POST /inference (helmet_detection)") as response:
            if response.status_code in [200, 404]:
                response.success()  # Both are acceptable
            else:
                response.failure(f"HTTP {response.status_code}")


@events.init_command_line_parser.add_listener
def _(parser):
    """Add custom command-line arguments."""
    parser.add_argument(
        "--target-model",
        type=str,
        default="fall_detection",
        help="Target model for testing (fall_detection, helmet_detection, etc.)"
    )


# Print test info on start
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Print test configuration on start."""
    print("\n" + "=" * 60)
    print("Ruth AI Unified Runtime - Load Test")
    print("=" * 60)
    print(f"Host: {environment.host}")
    print(f"Users: {environment.runner.target_user_count}")
    print(f"Spawn rate: {environment.runner.spawn_rate}")
    print(f"Run time: {environment.parsed_options.run_time}")
    print("=" * 60 + "\n")


# Print summary on stop
@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print test summary on stop."""
    stats = environment.stats

    print("\n" + "=" * 60)
    print("Load Test Summary")
    print("=" * 60)
    print(f"Total requests: {stats.total.num_requests}")
    print(f"Total failures: {stats.total.num_failures}")
    print(f"Failure rate: {stats.total.fail_ratio * 100:.2f}%")
    print(f"Median response time: {stats.total.median_response_time:.0f}ms")
    print(f"95th percentile: {stats.total.get_response_time_percentile(0.95):.0f}ms")
    print(f"99th percentile: {stats.total.get_response_time_percentile(0.99):.0f}ms")
    print(f"Average response time: {stats.total.avg_response_time:.0f}ms")
    print(f"Max response time: {stats.total.max_response_time:.0f}ms")
    print(f"Requests/sec: {stats.total.current_rps:.2f}")
    print("=" * 60 + "\n")

    # Check performance targets
    p50 = stats.total.median_response_time
    p99 = stats.total.get_response_time_percentile(0.99)
    error_rate = stats.total.fail_ratio * 100

    print("Performance Targets:")
    print(f"  p50 < 100ms: {'✓ PASS' if p50 < 100 else '✗ FAIL'} ({p50:.0f}ms)")
    print(f"  p99 < 500ms: {'✓ PASS' if p99 < 500 else '✗ FAIL'} ({p99:.0f}ms)")
    print(f"  Error rate < 1%: {'✓ PASS' if error_rate < 1 else '✗ FAIL'} ({error_rate:.2f}%)")
    print()
