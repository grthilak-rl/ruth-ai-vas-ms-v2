"""Database connection management for NLP Chat Service.

Read-only access to Ruth AI PostgreSQL database.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

# Global engine and session factory
_engine = None
_async_session_factory = None


async def init_database() -> None:
    """Initialize database connection pool."""
    global _engine, _async_session_factory

    settings = get_settings()
    database_url = str(settings.database_url)

    _engine = create_async_engine(
        database_url,
        pool_size=settings.database_pool_size,
        pool_pre_ping=True,
        echo=settings.is_development,
    )

    _async_session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    logger.info("Database connection pool initialized")


async def close_database() -> None:
    """Close database connections."""
    global _engine

    if _engine:
        await _engine.dispose()
        logger.info("Database connections closed")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for dependency injection."""
    if _async_session_factory is None:
        raise RuntimeError("Database not initialized")

    async with _async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
