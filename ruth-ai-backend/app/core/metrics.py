"""Prometheus-compatible metrics for Ruth AI Backend.

Provides:
- Thread-safe metrics registry
- Counters, histograms, and gauges with labels
- HTTP metrics middleware integration
- Domain service instrumentation helpers
- Prometheus text format exposition

Design Principles:
- Observability must be cheap
- Instrumentation is optional, never mandatory
- Failures in metrics NEVER affect core behavior
- Prefer explicit instrumentation over magic decorators

Usage:
    from app.core.metrics import (
        metrics_registry,
        http_requests_total,
        record_http_request,
        get_metrics_text,
    )

    # Record HTTP request
    record_http_request(method="GET", path="/api/v1/devices", status=200, duration=0.05)

    # Increment domain counter
    events_ingested_total.labels(event_type="fall_detected").inc()

    # Get Prometheus text format
    text = get_metrics_text()
"""

import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Generator

from app.core.logging import get_logger, get_request_id, set_request_id

logger = get_logger(__name__)


# =============================================================================
# Thread-Safe Metrics Registry
# =============================================================================


class MetricsRegistry:
    """Thread-safe registry for Prometheus-style metrics.

    Manages counters, gauges, and histograms with label support.
    All operations are thread-safe via internal locking.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._counters: dict[str, "Counter"] = {}
        self._gauges: dict[str, "Gauge"] = {}
        self._histograms: dict[str, "Histogram"] = {}

    def register_counter(
        self,
        name: str,
        description: str,
        labels: list[str] | None = None,
    ) -> "Counter":
        """Register a new counter metric."""
        with self._lock:
            if name in self._counters:
                return self._counters[name]
            counter = Counter(name, description, labels or [])
            self._counters[name] = counter
            return counter

    def register_gauge(
        self,
        name: str,
        description: str,
        labels: list[str] | None = None,
    ) -> "Gauge":
        """Register a new gauge metric."""
        with self._lock:
            if name in self._gauges:
                return self._gauges[name]
            gauge = Gauge(name, description, labels or [])
            self._gauges[name] = gauge
            return gauge

    def register_histogram(
        self,
        name: str,
        description: str,
        labels: list[str] | None = None,
        buckets: list[float] | None = None,
    ) -> "Histogram":
        """Register a new histogram metric."""
        with self._lock:
            if name in self._histograms:
                return self._histograms[name]
            histogram = Histogram(name, description, labels or [], buckets)
            self._histograms[name] = histogram
            return histogram

    def collect(self) -> list[str]:
        """Collect all metrics in Prometheus text format."""
        lines: list[str] = []
        with self._lock:
            for counter in self._counters.values():
                lines.extend(counter.to_prometheus())
            for gauge in self._gauges.values():
                lines.extend(gauge.to_prometheus())
            for histogram in self._histograms.values():
                lines.extend(histogram.to_prometheus())
        return lines


# Global registry
metrics_registry = MetricsRegistry()


# =============================================================================
# Metric Types
# =============================================================================


class LabeledMetric:
    """Base class for labeled metrics."""

    def __init__(
        self,
        name: str,
        description: str,
        label_names: list[str],
    ) -> None:
        self.name = name
        self.description = description
        self.label_names = label_names
        self._lock = threading.RLock()

    def _validate_labels(self, labels: dict[str, str]) -> None:
        """Validate that provided labels match expected label names."""
        if set(labels.keys()) != set(self.label_names):
            raise ValueError(
                f"Labels {set(labels.keys())} do not match expected {set(self.label_names)}"
            )

    def _labels_key(self, labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
        """Create a hashable key from labels."""
        return tuple(sorted(labels.items()))

    def _format_labels(self, labels: dict[str, str]) -> str:
        """Format labels for Prometheus output."""
        if not labels:
            return ""
        parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        return "{" + ",".join(parts) + "}"


class Counter(LabeledMetric):
    """Prometheus-style counter (monotonically increasing)."""

    def __init__(
        self,
        name: str,
        description: str,
        label_names: list[str],
    ) -> None:
        super().__init__(name, description, label_names)
        self._values: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)

    def labels(self, **kwargs: str) -> "CounterChild":
        """Get a counter child with specific label values."""
        return CounterChild(self, kwargs)

    def inc(self, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """Increment counter value."""
        labels = labels or {}
        if self.label_names and not labels:
            return  # Silently ignore if labels required but not provided
        if labels:
            self._validate_labels(labels)
        with self._lock:
            self._values[self._labels_key(labels)] += value

    def to_prometheus(self) -> list[str]:
        """Convert to Prometheus text format."""
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} counter",
        ]
        with self._lock:
            for labels_key, value in self._values.items():
                labels_dict = dict(labels_key)
                labels_str = self._format_labels(labels_dict)
                lines.append(f"{self.name}{labels_str} {value}")
        return lines


class CounterChild:
    """A counter instance with pre-bound labels."""

    def __init__(self, parent: Counter, labels: dict[str, str]) -> None:
        self._parent = parent
        self._labels = labels

    def inc(self, value: float = 1.0) -> None:
        """Increment counter value."""
        self._parent.inc(value, self._labels)


class Gauge(LabeledMetric):
    """Prometheus-style gauge (can go up and down)."""

    def __init__(
        self,
        name: str,
        description: str,
        label_names: list[str],
    ) -> None:
        super().__init__(name, description, label_names)
        self._values: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)

    def labels(self, **kwargs: str) -> "GaugeChild":
        """Get a gauge child with specific label values."""
        return GaugeChild(self, kwargs)

    def set(self, value: float, labels: dict[str, str] | None = None) -> None:
        """Set gauge value."""
        labels = labels or {}
        if self.label_names and not labels:
            return
        if labels:
            self._validate_labels(labels)
        with self._lock:
            self._values[self._labels_key(labels)] = value

    def inc(self, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """Increment gauge value."""
        labels = labels or {}
        if self.label_names and not labels:
            return
        if labels:
            self._validate_labels(labels)
        with self._lock:
            self._values[self._labels_key(labels)] += value

    def dec(self, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """Decrement gauge value."""
        labels = labels or {}
        if self.label_names and not labels:
            return
        if labels:
            self._validate_labels(labels)
        with self._lock:
            self._values[self._labels_key(labels)] -= value

    def to_prometheus(self) -> list[str]:
        """Convert to Prometheus text format."""
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} gauge",
        ]
        with self._lock:
            for labels_key, value in self._values.items():
                labels_dict = dict(labels_key)
                labels_str = self._format_labels(labels_dict)
                lines.append(f"{self.name}{labels_str} {value}")
        return lines


class GaugeChild:
    """A gauge instance with pre-bound labels."""

    def __init__(self, parent: Gauge, labels: dict[str, str]) -> None:
        self._parent = parent
        self._labels = labels

    def set(self, value: float) -> None:
        """Set gauge value."""
        self._parent.set(value, self._labels)

    def inc(self, value: float = 1.0) -> None:
        """Increment gauge value."""
        self._parent.inc(value, self._labels)

    def dec(self, value: float = 1.0) -> None:
        """Decrement gauge value."""
        self._parent.dec(value, self._labels)


# Default histogram buckets (in seconds)
DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]


class Histogram(LabeledMetric):
    """Prometheus-style histogram with configurable buckets."""

    def __init__(
        self,
        name: str,
        description: str,
        label_names: list[str],
        buckets: list[float] | None = None,
    ) -> None:
        super().__init__(name, description, label_names)
        self.buckets = sorted(buckets or DEFAULT_BUCKETS)
        # Per-label data: {labels_key: {"buckets": {...}, "sum": float, "count": int}}
        self._data: dict[tuple[tuple[str, str], ...], dict[str, Any]] = {}

    def _get_data(
        self, labels_key: tuple[tuple[str, str], ...]
    ) -> dict[str, Any]:
        """Get or create data for a label combination."""
        if labels_key not in self._data:
            self._data[labels_key] = {
                "buckets": {b: 0 for b in self.buckets},
                "sum": 0.0,
                "count": 0,
            }
        return self._data[labels_key]

    def labels(self, **kwargs: str) -> "HistogramChild":
        """Get a histogram child with specific label values."""
        return HistogramChild(self, kwargs)

    def observe(self, value: float, labels: dict[str, str] | None = None) -> None:
        """Observe a value."""
        labels = labels or {}
        if self.label_names and not labels:
            return
        if labels:
            self._validate_labels(labels)
        labels_key = self._labels_key(labels)
        with self._lock:
            data = self._get_data(labels_key)
            data["sum"] += value
            data["count"] += 1
            for bucket in self.buckets:
                if value <= bucket:
                    data["buckets"][bucket] += 1

    def to_prometheus(self) -> list[str]:
        """Convert to Prometheus text format."""
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} histogram",
        ]
        with self._lock:
            for labels_key, data in self._data.items():
                labels_dict = dict(labels_key)
                base_labels = self._format_labels(labels_dict)

                # Cumulative bucket counts
                cumulative = 0
                for bucket in self.buckets:
                    cumulative += data["buckets"][bucket]
                    if labels_dict:
                        bucket_labels = {**labels_dict, "le": str(bucket)}
                    else:
                        bucket_labels = {"le": str(bucket)}
                    labels_str = self._format_labels(bucket_labels)
                    lines.append(f"{self.name}_bucket{labels_str} {cumulative}")

                # +Inf bucket
                if labels_dict:
                    inf_labels = {**labels_dict, "le": "+Inf"}
                else:
                    inf_labels = {"le": "+Inf"}
                labels_str = self._format_labels(inf_labels)
                lines.append(f"{self.name}_bucket{labels_str} {data['count']}")

                # Sum and count
                lines.append(f"{self.name}_sum{base_labels} {data['sum']}")
                lines.append(f"{self.name}_count{base_labels} {data['count']}")
        return lines


class HistogramChild:
    """A histogram instance with pre-bound labels."""

    def __init__(self, parent: Histogram, labels: dict[str, str]) -> None:
        self._parent = parent
        self._labels = labels

    def observe(self, value: float) -> None:
        """Observe a value."""
        self._parent.observe(value, self._labels)

    @contextmanager
    def time(self) -> Generator[None, None, None]:
        """Context manager to measure and observe duration."""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start
            self.observe(duration)


# =============================================================================
# Pre-registered Metrics
# =============================================================================

# --- API Layer ---
http_requests_total = metrics_registry.register_counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

http_request_latency_seconds = metrics_registry.register_histogram(
    "http_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)

# --- Domain Services ---
events_ingested_total = metrics_registry.register_counter(
    "events_ingested_total",
    "Total events ingested from AI Runtime",
    ["event_type"],
)

violations_created_total = metrics_registry.register_counter(
    "violations_created_total",
    "Total violations created",
    ["violation_type"],
)

evidence_created_total = metrics_registry.register_counter(
    "evidence_created_total",
    "Total evidence items created",
    ["evidence_type", "status"],
)

# --- VAS Integration ---
vas_requests_total = metrics_registry.register_counter(
    "vas_requests_total",
    "Total VAS API requests",
    ["endpoint", "status"],
)

vas_request_latency_seconds = metrics_registry.register_histogram(
    "vas_request_latency_seconds",
    "VAS API request latency in seconds",
    ["endpoint"],
)

# --- AI Runtime Integration ---
ai_runtime_requests_total = metrics_registry.register_counter(
    "ai_runtime_requests_total",
    "Total AI Runtime requests",
    ["operation", "status"],
)

ai_runtime_latency_seconds = metrics_registry.register_histogram(
    "ai_runtime_latency_seconds",
    "AI Runtime request latency in seconds",
    ["operation"],
)

# --- Active connections/sessions ---
active_stream_sessions = metrics_registry.register_gauge(
    "active_stream_sessions",
    "Currently active stream sessions",
    [],
)


# =============================================================================
# Helper Functions
# =============================================================================


def record_http_request(
    method: str,
    path: str,
    status: int,
    duration: float,
) -> None:
    """Record an HTTP request for metrics.

    Safe to call - failures are logged but never raised.

    Args:
        method: HTTP method (GET, POST, etc.)
        path: Request path (normalized)
        status: HTTP status code
        duration: Request duration in seconds
    """
    try:
        # Normalize path to reduce cardinality
        normalized_path = _normalize_path(path)
        status_str = str(status)

        http_requests_total.labels(
            method=method,
            path=normalized_path,
            status=status_str,
        ).inc()

        http_request_latency_seconds.labels(
            method=method,
            path=normalized_path,
        ).observe(duration)
    except Exception as e:
        logger.warning("Failed to record HTTP metrics", error=str(e))


def record_vas_request(
    endpoint: str,
    status: str,
    duration: float,
) -> None:
    """Record a VAS API request for metrics.

    Args:
        endpoint: VAS endpoint (e.g., "/v2/streams")
        status: Status ("success" or "error")
        duration: Request duration in seconds
    """
    try:
        vas_requests_total.labels(endpoint=endpoint, status=status).inc()
        vas_request_latency_seconds.labels(endpoint=endpoint).observe(duration)
    except Exception as e:
        logger.warning("Failed to record VAS metrics", error=str(e))


def record_ai_runtime_request(
    operation: str,
    status: str,
    duration: float,
) -> None:
    """Record an AI Runtime request for metrics.

    Args:
        operation: Operation name (e.g., "inference", "health")
        status: Status ("success" or "error")
        duration: Request duration in seconds
    """
    try:
        ai_runtime_requests_total.labels(operation=operation, status=status).inc()
        ai_runtime_latency_seconds.labels(operation=operation).observe(duration)
    except Exception as e:
        logger.warning("Failed to record AI Runtime metrics", error=str(e))


def record_event_ingested(event_type: str) -> None:
    """Record an event ingestion.

    Args:
        event_type: Type of event (e.g., "fall_detected")
    """
    try:
        events_ingested_total.labels(event_type=event_type).inc()
    except Exception as e:
        logger.warning("Failed to record event metric", error=str(e))


def record_violation_created(violation_type: str) -> None:
    """Record a violation creation.

    Args:
        violation_type: Type of violation (e.g., "fall_detected")
    """
    try:
        violations_created_total.labels(violation_type=violation_type).inc()
    except Exception as e:
        logger.warning("Failed to record violation metric", error=str(e))


def record_evidence_created(evidence_type: str, status: str) -> None:
    """Record an evidence creation.

    Args:
        evidence_type: Type of evidence (e.g., "snapshot", "bookmark")
        status: Creation status (e.g., "pending", "ready", "failed")
    """
    try:
        evidence_created_total.labels(evidence_type=evidence_type, status=status).inc()
    except Exception as e:
        logger.warning("Failed to record evidence metric", error=str(e))


def _normalize_path(path: str) -> str:
    """Normalize path to reduce cardinality.

    Replaces UUIDs and numeric IDs with placeholders.

    Args:
        path: Original request path

    Returns:
        Normalized path
    """
    import re

    # Replace UUIDs
    path = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "{id}",
        path,
        flags=re.IGNORECASE,
    )
    # Replace numeric IDs
    path = re.sub(r"/\d+(/|$)", "/{id}\\1", path)
    return path


def get_metrics_text() -> str:
    """Get all metrics in Prometheus text exposition format.

    Returns:
        Prometheus text format string
    """
    try:
        lines = metrics_registry.collect()
        return "\n".join(lines) + "\n"
    except Exception as e:
        logger.error("Failed to collect metrics", error=str(e))
        return "# Error collecting metrics\n"


# =============================================================================
# Correlation ID Helpers
# =============================================================================


def ensure_correlation_id() -> str:
    """Ensure a correlation ID exists in context.

    If no request_id is set (e.g., background task), generates
    a synthetic one prefixed with 'bg-'.

    Returns:
        The correlation ID
    """
    request_id = get_request_id()
    if request_id:
        return request_id

    # Generate synthetic ID for background context
    synthetic_id = f"bg-{uuid.uuid4()}"
    set_request_id(synthetic_id)
    return synthetic_id


@contextmanager
def correlation_context(correlation_id: str | None = None) -> Generator[str, None, None]:
    """Context manager for correlation ID scope.

    Useful for background tasks or service-layer operations
    that need a correlation ID but may not have one.

    Args:
        correlation_id: Optional explicit ID, otherwise generated

    Yields:
        The correlation ID in use
    """
    if correlation_id:
        set_request_id(correlation_id)
        yield correlation_id
    else:
        cid = ensure_correlation_id()
        yield cid


# =============================================================================
# Metrics Endpoint Router
# =============================================================================


def create_metrics_router():
    """Create FastAPI router for metrics endpoint.

    Returns:
        FastAPI APIRouter with /metrics endpoint
    """
    from fastapi import APIRouter
    from fastapi.responses import PlainTextResponse

    router = APIRouter(tags=["Observability"])

    @router.get(
        "/metrics",
        response_class=PlainTextResponse,
        summary="Prometheus metrics",
        description="Returns metrics in Prometheus text exposition format.",
    )
    async def get_metrics() -> PlainTextResponse:
        """Get Prometheus metrics."""
        content = get_metrics_text()
        return PlainTextResponse(
            content=content,
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return router
