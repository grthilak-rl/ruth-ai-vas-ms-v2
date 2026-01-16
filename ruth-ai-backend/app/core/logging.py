"""Structured JSON logging with request_id propagation.

Provides:
- JSON-formatted log output to stdout
- Request ID propagation via contextvars
- Configurable log levels
- Structured fields for observability
"""

import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.core.config import get_settings

# Context variable for request ID propagation
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Get the current request ID from context."""
    return request_id_ctx.get()


def set_request_id(request_id: str) -> None:
    """Set the request ID in context."""
    request_id_ctx.set(request_id)


def add_request_id(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add request_id to log events if available."""
    request_id = get_request_id()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def add_timestamp(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add ISO 8601 timestamp to log events."""
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def add_service_info(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add service metadata to log events."""
    event_dict["service"] = "ruth-ai-backend"
    return event_dict


def configure_logging() -> None:
    """Configure structured logging for the application.

    Sets up structlog with JSON output to stdout.
    Log level is determined by settings.
    """
    settings = get_settings()

    # Map string log level to logging constant
    log_level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    log_level = log_level_map.get(settings.ruth_ai_log_level, logging.INFO)

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Shared processors for all log entries
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        add_timestamp,
        add_service_info,
        add_request_id,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    # Choose renderer based on format setting
    if settings.ruth_ai_log_format == "json":
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure formatter for stdlib handlers
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Apply formatter to root logger
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a configured logger instance.

    Args:
        name: Logger name (module name recommended)

    Returns:
        Configured structlog BoundLogger instance
    """
    return structlog.get_logger(name)


def log_with_context(
    logger: structlog.stdlib.BoundLogger,
    level: str,
    message: str,
    **kwargs: Any,
) -> None:
    """Log a message with additional context.

    Args:
        logger: Logger instance
        level: Log level (debug, info, warning, error)
        message: Log message
        **kwargs: Additional context fields
    """
    log_method = getattr(logger, level, logger.info)
    log_method(message, **kwargs)
