"""
Ruth AI Unified Runtime - Concurrent Inference Tests

Pytest-based concurrent stress tests using asyncio.

Run tests:
    pytest test_concurrent_inference.py -v -s

Test scenarios:
- Concurrent requests to single model
- Concurrent requests to multiple models
- Sustained load over time
- Memory leak detection
"""

import asyncio
import base64
import io
import time
from datetime import datetime
from typing import List

import httpx
import numpy as np
import pytest
from PIL import Image


BASE_URL = "http://localhost:8000"


def create_test_frame_base64(width=640, height=480):
    """Create a test frame encoded as base64."""
    img = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
    img_rgb = img[:, :, ::-1]
    img_pil = Image.fromarray(img_rgb)

    buffer = io.BytesIO()
    img_pil.save(buffer, format="JPEG", quality=85)
    img_bytes = buffer.getvalue()

    return base64.b64encode(img_bytes).decode('utf-8')


async def submit_inference_request(client: httpx.AsyncClient, model_id="fall_detection"):
    """
    Submit a single inference request.

    Args:
        client: HTTP client
        model_id: Target model

    Returns:
        Response data and timing
    """
    frame_base64 = create_test_frame_base64()

    payload = {
        "stream_id": "550e8400-e29b-41d4-a716-446655440000",
        "frame_base64": frame_base64,
        "frame_format": "jpeg",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "model_id": model_id,
        "metadata": {}
    }

    start_time = time.time()

    try:
        response = await client.post(f"{BASE_URL}/inference", json=payload, timeout=30.0)
        duration = time.time() - start_time

        return {
            "status_code": response.status_code,
            "duration": duration,
            "data": response.json() if response.status_code == 200 else None,
            "error": None
        }
    except Exception as e:
        duration = time.time() - start_time
        return {
            "status_code": 0,
            "duration": duration,
            "data": None,
            "error": str(e)
        }


@pytest.mark.asyncio
async def test_concurrent_single_model_10():
    """Test 10 concurrent requests to single model."""
    async with httpx.AsyncClient() as client:
        tasks = [submit_inference_request(client) for _ in range(10)]
        results = await asyncio.gather(*tasks)

    # Verify all succeeded
    success_count = sum(1 for r in results if r["status_code"] == 200)
    error_count = sum(1 for r in results if r["status_code"] != 200)

    print(f"\n10 Concurrent Requests:")
    print(f"  Success: {success_count}/10")
    print(f"  Errors: {error_count}/10")

    # Calculate latency stats
    durations = [r["duration"] * 1000 for r in results if r["status_code"] == 200]
    if durations:
        print(f"  Min latency: {min(durations):.0f}ms")
        print(f"  Max latency: {max(durations):.0f}ms")
        print(f"  Avg latency: {sum(durations)/len(durations):.0f}ms")

    # Assert success rate > 90%
    assert success_count >= 9, f"Expected >= 9 successes, got {success_count}"


@pytest.mark.asyncio
async def test_concurrent_single_model_50():
    """Test 50 concurrent requests to single model."""
    async with httpx.AsyncClient() as client:
        tasks = [submit_inference_request(client) for _ in range(50)]
        results = await asyncio.gather(*tasks)

    success_count = sum(1 for r in results if r["status_code"] == 200)
    error_count = sum(1 for r in results if r["status_code"] != 200)

    print(f"\n50 Concurrent Requests:")
    print(f"  Success: {success_count}/50")
    print(f"  Errors: {error_count}/50")

    # Calculate latency stats
    durations = [r["duration"] * 1000 for r in results if r["status_code"] == 200]
    if durations:
        durations_sorted = sorted(durations)
        p50 = durations_sorted[len(durations_sorted) // 2]
        p95 = durations_sorted[int(len(durations_sorted) * 0.95)]
        p99 = durations_sorted[int(len(durations_sorted) * 0.99)]

        print(f"  p50 latency: {p50:.0f}ms")
        print(f"  p95 latency: {p95:.0f}ms")
        print(f"  p99 latency: {p99:.0f}ms")

    # Assert success rate > 90%
    assert success_count >= 45, f"Expected >= 45 successes, got {success_count}"


@pytest.mark.asyncio
async def test_sustained_load_5_minutes():
    """Test sustained load (5 requests/sec for 60 seconds)."""
    print("\nSustained Load Test (5 req/sec for 60s)...")

    async with httpx.AsyncClient() as client:
        results = []
        start_time = time.time()
        request_interval = 0.2  # 5 requests/sec
        duration_seconds = 60

        request_count = 0
        while time.time() - start_time < duration_seconds:
            # Submit request
            task = submit_inference_request(client)
            result = await task
            results.append(result)
            request_count += 1

            # Wait for next interval
            await asyncio.sleep(request_interval)

            # Print progress every 10 seconds
            elapsed = time.time() - start_time
            if int(elapsed) % 10 == 0 and elapsed > 1:
                success_so_far = sum(1 for r in results if r["status_code"] == 200)
                print(f"  {int(elapsed)}s: {success_so_far}/{len(results)} successful")

    total_duration = time.time() - start_time
    success_count = sum(1 for r in results if r["status_code"] == 200)
    error_count = len(results) - success_count

    print(f"\nSustained Load Results:")
    print(f"  Duration: {total_duration:.1f}s")
    print(f"  Total requests: {len(results)}")
    print(f"  Success: {success_count}")
    print(f"  Errors: {error_count}")
    print(f"  Success rate: {success_count/len(results)*100:.1f}%")
    print(f"  Requests/sec: {len(results)/total_duration:.2f}")

    # Calculate latency stats
    durations = [r["duration"] * 1000 for r in results if r["status_code"] == 200]
    if durations:
        print(f"  Avg latency: {sum(durations)/len(durations):.0f}ms")

    # Assert success rate > 95%
    assert success_count / len(results) >= 0.95, f"Success rate too low: {success_count}/{len(results)}"


@pytest.mark.asyncio
async def test_burst_traffic():
    """Test burst traffic pattern (50 requests, wait, repeat 3 times)."""
    print("\nBurst Traffic Test (50 req bursts, 3 iterations)...")

    async with httpx.AsyncClient() as client:
        all_results = []

        for iteration in range(3):
            print(f"  Burst {iteration + 1}/3...")

            # Send burst
            tasks = [submit_inference_request(client) for _ in range(50)]
            results = await asyncio.gather(*tasks)
            all_results.extend(results)

            success = sum(1 for r in results if r["status_code"] == 200)
            print(f"    Success: {success}/50")

            # Wait between bursts
            if iteration < 2:
                await asyncio.sleep(10)

    success_count = sum(1 for r in all_results if r["status_code"] == 200)
    print(f"\nTotal: {success_count}/{len(all_results)} successful")

    # Assert success rate > 90%
    assert success_count / len(all_results) >= 0.9


@pytest.mark.asyncio
async def test_memory_stability():
    """Test memory stability over many requests."""
    print("\nMemory Stability Test (500 requests)...")

    async with httpx.AsyncClient() as client:
        # Get initial memory from health endpoint
        health_response = await client.get(f"{BASE_URL}/health?verbose=true")
        initial_health = health_response.json() if health_response.status_code == 200 else None

        # Submit many requests
        batch_size = 50
        total_requests = 500
        all_results = []

        for batch_num in range(total_requests // batch_size):
            tasks = [submit_inference_request(client) for _ in range(batch_size)]
            results = await asyncio.gather(*tasks)
            all_results.extend(results)

            if (batch_num + 1) % 2 == 0:
                completed = (batch_num + 1) * batch_size
                success = sum(1 for r in all_results if r["status_code"] == 200)
                print(f"  {completed}/{total_requests} requests: {success} successful")

        # Get final memory
        health_response = await client.get(f"{BASE_URL}/health?verbose=true")
        final_health = health_response.json() if health_response.status_code == 200 else None

        success_count = sum(1 for r in all_results if r["status_code"] == 200)
        print(f"\nCompleted {len(all_results)} requests: {success_count} successful")

        # Check memory usage if GPU available
        if initial_health and final_health and "gpu_devices" in initial_health:
            if initial_health["gpu_devices"] and final_health["gpu_devices"]:
                initial_mem = initial_health["gpu_devices"][0]["used_memory_mb"]
                final_mem = final_health["gpu_devices"][0]["used_memory_mb"]
                mem_increase = final_mem - initial_mem

                print(f"  GPU memory: {initial_mem:.0f}MB → {final_mem:.0f}MB (Δ{mem_increase:+.0f}MB)")

                # Assert memory didn't increase by more than 500MB (reasonable leak threshold)
                assert mem_increase < 500, f"Potential memory leak: {mem_increase:.0f}MB increase"

    assert success_count / len(all_results) >= 0.95


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
