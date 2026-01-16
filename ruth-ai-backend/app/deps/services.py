"""Service dependency injection for FastAPI routes.

Provides factory functions for injecting domain services into API endpoints.
Services are constructed with their required dependencies (VAS client, DB session).
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.deps.db import get_db
from app.integrations.nlp_chat import NLPChatClient
from app.integrations.vas import VASClient
from app.services import (
    DeviceService,
    EvidenceService,
    EventIngestionService,
    StreamService,
    ViolationService,
)


# -----------------------------------------------------------------------------
# VAS Client Dependency
# -----------------------------------------------------------------------------

# Global VAS client instance (initialized on startup)
_vas_client: VASClient | None = None


def set_vas_client(client: VASClient) -> None:
    """Set the global VAS client instance (called during app startup)."""
    global _vas_client
    _vas_client = client


def get_vas_client() -> VASClient:
    """Get the VAS client instance.

    Raises:
        RuntimeError: If VAS client is not initialized
    """
    if _vas_client is None:
        raise RuntimeError("VAS client not initialized")
    return _vas_client


def get_vas_client_optional() -> VASClient | None:
    """Get the VAS client instance if available.

    Returns:
        VAS client or None if not initialized
    """
    return _vas_client


# -----------------------------------------------------------------------------
# Redis Client Dependency
# -----------------------------------------------------------------------------

# Global Redis client instance (initialized on startup)
_redis_client: Redis | None = None


def set_redis_client(client: Redis) -> None:
    """Set the global Redis client instance (called during app startup)."""
    global _redis_client
    _redis_client = client


def get_redis_client() -> Redis:
    """Get the Redis client instance.

    Raises:
        RuntimeError: If Redis client is not initialized
    """
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized")
    return _redis_client


def get_redis_client_optional() -> Redis | None:
    """Get the Redis client instance if available.

    Returns:
        Redis client or None if not initialized
    """
    return _redis_client


# -----------------------------------------------------------------------------
# NLP Chat Client Dependency
# -----------------------------------------------------------------------------

# Global NLP Chat client instance (initialized on startup)
_nlp_chat_client: NLPChatClient | None = None


def set_nlp_chat_client(client: NLPChatClient) -> None:
    """Set the global NLP Chat client instance (called during app startup)."""
    global _nlp_chat_client
    _nlp_chat_client = client


def get_nlp_chat_client() -> NLPChatClient:
    """Get the NLP Chat client instance.

    Raises:
        RuntimeError: If NLP Chat client is not initialized
    """
    if _nlp_chat_client is None:
        raise RuntimeError("NLP Chat client not initialized")
    return _nlp_chat_client


def get_nlp_chat_client_optional() -> NLPChatClient | None:
    """Get the NLP Chat client instance if available.

    Returns:
        NLP Chat client or None if not initialized
    """
    return _nlp_chat_client


# -----------------------------------------------------------------------------
# Service Dependencies
# -----------------------------------------------------------------------------


async def get_device_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[DeviceService, None]:
    """FastAPI dependency for DeviceService.

    Args:
        db: Database session

    Yields:
        Configured DeviceService instance
    """
    vas_client = get_vas_client()
    yield DeviceService(vas_client, db)


async def get_stream_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[StreamService, None]:
    """FastAPI dependency for StreamService.

    Args:
        db: Database session

    Yields:
        Configured StreamService instance
    """
    vas_client = get_vas_client()
    # AI Runtime client is optional for stream management
    yield StreamService(vas_client, None, db)


async def get_violation_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[ViolationService, None]:
    """FastAPI dependency for ViolationService.

    Args:
        db: Database session

    Yields:
        Configured ViolationService instance with EvidenceService for auto-capture
    """
    vas_client = get_vas_client()
    evidence_service = EvidenceService(vas_client, db)
    yield ViolationService(db, evidence_service=evidence_service)


async def get_evidence_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[EvidenceService, None]:
    """FastAPI dependency for EvidenceService.

    Args:
        db: Database session

    Yields:
        Configured EvidenceService instance
    """
    vas_client = get_vas_client()
    yield EvidenceService(vas_client, db)


async def get_event_ingestion_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[EventIngestionService, None]:
    """FastAPI dependency for EventIngestionService.

    Args:
        db: Database session

    Yields:
        Configured EventIngestionService instance
    """
    vas_client = get_vas_client()
    device_service = DeviceService(vas_client, db)
    stream_service = StreamService(vas_client, None, db)
    evidence_service = EvidenceService(vas_client, db)
    violation_service = ViolationService(db, evidence_service=evidence_service)
    yield EventIngestionService(
        device_service,
        stream_service,
        db,
        violation_service=violation_service,
    )


# Type aliases for dependency injection
VASClientDep = Annotated[VASClient, Depends(get_vas_client)]
DeviceServiceDep = Annotated[DeviceService, Depends(get_device_service)]
StreamServiceDep = Annotated[StreamService, Depends(get_stream_service)]
ViolationServiceDep = Annotated[ViolationService, Depends(get_violation_service)]
EvidenceServiceDep = Annotated[EvidenceService, Depends(get_evidence_service)]
EventIngestionServiceDep = Annotated[
    EventIngestionService, Depends(get_event_ingestion_service)
]
NLPChatClientDep = Annotated[NLPChatClient, Depends(get_nlp_chat_client)]
