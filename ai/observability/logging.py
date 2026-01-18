"""
Ruth AI Unified Runtime - Structured Logging

Provides JSON-formatted structured logging with request correlation and
consistent field names across all log entries.

Features:
- JSON output for machine parsing
- Request ID propagation (correlation)
- Performance timing
- Sensitive data redaction
- Consistent field naming

Usage:
    from ai.observability.logging import get_logger, configure_logging

    # Configure at startup
    configure_logging(level="INFO", format="json")

    # Use in code
    logger = get_logger(__name__)
    logger.info("Inference completed", extra={
        "request_id": "req-123",
        "model_id": "fall_detection",
        "inference_time_ms": 45.2,
        "status": "success"
    })

Output:
    {
        "timestamp": "2026-01-18T10:30:00.123Z",
        "level": "INFO",
        "logger": "ai.server.routes.inference",
        "request_id": "req-123",
        "message": "Inference completed",
        "model_id": "fall_detection",
        "inference_time_ms": 45.2,
        "status": "success"
    }
"""

import json
import logging
import sys
import time
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Dict, Optional

# Context variable for request ID (thread-safe)
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging.

    Formats log records as JSON with consistent field names.
    """

    RESERVED_FIELDS = {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "thread",
        "threadName",
        "exc_info",
        "exc_text",
        "stack_info",
    }

    def __init__(self, redact_fields: Optional[list] = None):
        """
        Initialize JSON formatter.

        Args:
            redact_fields: List of field names to redact (truncate)
        """
        super().__init__()
        self.redact_fields = redact_fields or ["frame_base64", "password", "token"]

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON string
        """
        # Base log entry
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add request ID if available
        request_id = request_id_var.get()
        if request_id:
            log_entry["request_id"] = request_id

        # Add extra fields from record
        for key, value in record.__dict__.items():
            # Skip reserved fields
            if key in self.RESERVED_FIELDS:
                continue

            # Redact sensitive fields
            if key in self.redact_fields and isinstance(value, str):
                if len(value) > 50:
                    value = value[:50] + "...[REDACTED]"

            log_entry[key] = value

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


class RequestIdFilter(logging.Filter):
    """
    Filter to add request ID to log records.

    Pulls request ID from context variable and adds to record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Add request ID to record if available.

        Args:
            record: Log record to filter

        Returns:
            True (always passes)
        """
        request_id = request_id_var.get()
        if request_id:
            record.request_id = request_id
        return True


def configure_logging(
    level: str = "INFO",
    format: str = "json",
    redact_fields: Optional[list] = None,
) -> None:
    """
    Configure structured logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format: Log format ("json" or "text")
        redact_fields: List of field names to redact
    """
    # Get root logger
    root_logger = logging.getLogger()

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)

    # Set formatter
    if format.lower() == "json":
        formatter = JsonFormatter(redact_fields=redact_fields)
    else:
        # Text format for development
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    handler.setFormatter(formatter)

    # Add request ID filter
    handler.addFilter(RequestIdFilter())

    # Add handler to root logger
    root_logger.addHandler(handler)

    # Set log level
    log_level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(log_level)

    # Configure specific loggers
    # Silence noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def set_request_id(request_id: str) -> None:
    """
    Set request ID in context.

    Args:
        request_id: Request ID to set
    """
    request_id_var.set(request_id)


def get_request_id() -> Optional[str]:
    """
    Get current request ID from context.

    Returns:
        Request ID or None
    """
    return request_id_var.get()


def clear_request_id() -> None:
    """Clear request ID from context."""
    request_id_var.set(None)


class LogTimer:
    """
    Context manager for timing operations and logging duration.

    Usage:
        with LogTimer(logger, "model_loading", model_id="fall_detection"):
            # Load model
            pass

        # Logs: {"message": "model_loading", "duration_ms": 1234.5, "model_id": "fall_detection"}
    """

    def __init__(
        self,
        logger: logging.Logger,
        operation: str,
        level: int = logging.INFO,
        **extra_fields
    ):
        """
        Initialize log timer.

        Args:
            logger: Logger instance
            operation: Operation name (used in message)
            level: Log level
            **extra_fields: Additional fields to include in log
        """
        self.logger = logger
        self.operation = operation
        self.level = level
        self.extra_fields = extra_fields
        self.start_time = None

    def __enter__(self):
        """Start timer."""
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop timer and log duration."""
        duration_ms = (time.time() - self.start_time) * 1000

        log_data = {
            "duration_ms": round(duration_ms, 2),
            **self.extra_fields
        }

        if exc_type is None:
            # Success
            self.logger.log(
                self.level,
                f"{self.operation} completed",
                extra=log_data
            )
        else:
            # Error occurred
            log_data["error"] = str(exc_val)
            self.logger.error(
                f"{self.operation} failed",
                extra=log_data,
                exc_info=True
            )


def truncate_large_data(data: Any, max_length: int = 100) -> Any:
    """
    Truncate large data for logging.

    Args:
        data: Data to potentially truncate
        max_length: Maximum length for strings

    Returns:
        Truncated data
    """
    if isinstance(data, str) and len(data) > max_length:
        return data[:max_length] + f"...[{len(data)} bytes total]"
    elif isinstance(data, (bytes, bytearray)) and len(data) > max_length:
        return f"<binary data: {len(data)} bytes>"
    elif isinstance(data, dict):
        return {k: truncate_large_data(v, max_length) for k, v in data.items()}
    elif isinstance(data, list):
        return [truncate_large_data(item, max_length) for item in data]
    else:
        return data
