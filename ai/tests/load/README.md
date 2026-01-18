# Ruth AI Unified Runtime - Load Testing

Performance and stress testing for the unified AI runtime.

## Prerequisites

```bash
pip install locust httpx pytest pytest-asyncio numpy pillow
```

## Running Load Tests

### Locust HTTP Load Tests

Locust provides a web UI and distributed load testing capabilities.

#### Baseline Test (1 user, 60 seconds)

```bash
locust -f locustfile.py --host=http://localhost:8000 \
    --users=1 --spawn-rate=1 --run-time=60s --headless
```

#### Ramp-up Test (1→20 users over 120s)

```bash
locust -f locustfile.py --host=http://localhost:8000 \
    --users=20 --spawn-rate=1 --run-time=300s --headless
```

#### Sustained Load (20 users, 5 minutes)

```bash
locust -f locustfile.py --host=http://localhost:8000 \
    --users=20 --spawn-rate=5 --run-time=300s --headless
```

#### Burst Traffic (50 users, 2 minutes)

```bash
locust -f locustfile.py --host=http://localhost:8000 \
    --users=50 --spawn-rate=10 --run-time=120s --headless
```

#### With Web UI (for interactive testing)

```bash
locust -f locustfile.py --host=http://localhost:8000
# Then open http://localhost:8089 in your browser
```

### Pytest Concurrent Tests

Pytest provides programmatic concurrent stress tests.

#### Run all tests

```bash
pytest test_concurrent_inference.py -v -s
```

#### Run specific test

```bash
# Test 10 concurrent requests
pytest test_concurrent_inference.py::test_concurrent_single_model_10 -v -s

# Test 50 concurrent requests
pytest test_concurrent_inference.py::test_concurrent_single_model_50 -v -s

# Test sustained load (5 min)
pytest test_concurrent_inference.py::test_sustained_load_5_minutes -v -s

# Test burst traffic
pytest test_concurrent_inference.py::test_burst_traffic -v -s

# Test memory stability
pytest test_concurrent_inference.py::test_memory_stability -v -s
```

## Test Scenarios

### 1. Baseline (locustfile.py)

- **Users**: 1
- **Duration**: 60 seconds
- **Purpose**: Establish baseline performance
- **Expected**: p50 < 50ms, p99 < 100ms, 0% errors

### 2. Ramp-up (locustfile.py)

- **Users**: 1→20 (linear ramp)
- **Duration**: 300 seconds (5 minutes)
- **Purpose**: Test scaling behavior
- **Expected**: Graceful degradation, < 1% errors

### 3. Sustained Load (locustfile.py)

- **Users**: 20 constant
- **Duration**: 300 seconds (5 minutes)
- **Purpose**: Stability under load
- **Expected**: Stable latency, no memory leaks, < 1% errors

### 4. Burst Traffic (locustfile.py)

- **Users**: 50
- **Duration**: 120 seconds
- **Purpose**: Test spike handling
- **Expected**: Some queue rejections OK, < 5% errors

### 5. Multi-Model (locustfile.py: MultiModelUser)

- **Users**: 20
- **Duration**: 300 seconds
- **Purpose**: Test isolation between models
- **Expected**: Models don't interfere, < 1% errors

### 6. Concurrent Stress (test_concurrent_inference.py)

- **Scenarios**: 10, 50, 100 concurrent requests
- **Purpose**: Test concurrent execution
- **Expected**: > 90% success rate, p99 < 500ms

### 7. Memory Stability (test_concurrent_inference.py)

- **Requests**: 500 total
- **Purpose**: Detect memory leaks
- **Expected**: Memory increase < 500MB, no crashes

## Performance Targets

| Metric | Target | Stretch Goal |
|--------|--------|--------------|
| p50 latency | < 100ms | < 50ms |
| p99 latency | < 500ms | < 200ms |
| Error rate | < 1% | < 0.1% |
| Throughput | 10 req/s | 50 req/s |
| Memory leak | < 500MB over 5min | 0 MB |

## Interpreting Results

### Locust Output

```
Name                     # reqs  # fails  Avg  Min  Max    p50    p95    p99
POST /inference           1000      5     85    42   450    80     150    200
GET /health               100       0     12    8    25     10     18     22
```

**Good**: p95 < 200ms, error rate < 1%
**Degraded**: p95 200-500ms, error rate 1-5%
**Bad**: p95 > 500ms, error rate > 5%

### Pytest Output

```
10 Concurrent Requests:
  Success: 10/10
  Min latency: 45ms
  Max latency: 120ms
  Avg latency: 78ms

✓ PASS
```

## Monitoring During Tests

### Check Health Endpoint

```bash
# Basic health
curl http://localhost:8000/health

# Detailed (GPU, per-model stats)
curl http://localhost:8000/health?verbose=true
```

### Check Metrics

```bash
# Prometheus metrics
curl http://localhost:8000/metrics | grep inference
```

### Watch Logs

```bash
# If running in Docker
docker logs -f unified-runtime --tail=100

# If running locally
tail -f logs/runtime.log | jq .
```

### Monitor GPU

```bash
# If GPU available
nvidia-smi -l 1

# Or watch GPU memory
watch -n 1 'nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv'
```

## Troubleshooting

### High Error Rates

**Symptom**: > 5% errors during load test

**Possible causes**:
- Runtime not started: `curl http://localhost:8000/health`
- Concurrency limit hit: Check `MAX_CONCURRENT_INFERENCES` env var
- GPU OOM: Check `curl http://localhost:8000/health?verbose=true`
- Model not loaded: Check `/capabilities` endpoint

### High Latency

**Symptom**: p99 > 1000ms

**Possible causes**:
- CPU fallback (slower than GPU): Check GPU status in `/health?verbose=true`
- Disk I/O (model loading): Check if models are in memory
- Network latency: Run test on localhost
- Queueing: Increase `MAX_CONCURRENT_INFERENCES`

### Memory Leaks

**Symptom**: Memory increasing over time

**Check**:
```bash
# GPU memory
nvidia-smi -l 1

# System memory
watch -n 1 free -m

# Health endpoint
curl http://localhost:8000/health?verbose=true | jq '.gpu_devices[0].used_memory_mb'
```

**Fixes**:
- Ensure models are released properly
- Check for frame data accumulation
- Verify GPU cache is cleared

## CI/CD Integration

### GitHub Actions Example

```yaml
- name: Run load tests
  run: |
    # Start runtime
    docker-compose up -d unified-runtime

    # Wait for healthy
    timeout 60 bash -c 'until curl -f http://localhost:8000/health; do sleep 1; done'

    # Run load test
    locust -f ai/tests/load/locustfile.py --host=http://localhost:8000 \
      --users=10 --spawn-rate=2 --run-time=120s --headless

    # Check exit code (0 = success)
    if [ $? -ne 0 ]; then
      echo "Load test failed"
      exit 1
    fi
```

## Performance Baseline

Record baseline performance for regression detection:

```bash
# Run baseline and save results
locust -f locustfile.py --host=http://localhost:8000 \
    --users=10 --spawn-rate=2 --run-time=120s --headless \
    --csv=baseline_results

# Results saved to:
# - baseline_results_stats.csv
# - baseline_results_stats_history.csv
# - baseline_results_failures.csv
```

Compare against future runs to detect performance regressions.
