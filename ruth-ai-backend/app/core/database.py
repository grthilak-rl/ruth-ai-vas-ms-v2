"""Async database session setup using SQLAlchemy.

Provides:
- Async engine creation
- Async session factory
- No models defined here (deferred to Phase 4+)
"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Global engine and session factory (initialized during lifespan)
_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine | None:
    """Get the database engine instance.

    Returns None if not initialized.
    """
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """Get the session factory instance.

    Returns None if not initialized.
    """
    return _async_session_factory


async def init_database() -> None:
    """Initialize the database engine and session factory.

    Called during application startup.
    Creates async engine with connection pooling.
    """
    global _engine, _async_session_factory

    settings = get_settings()

    logger.info(
        "Initializing database connection",
        pool_size=settings.database_pool_size,
        pool_overflow=settings.database_pool_overflow,
    )

    # Create async engine
    _engine = create_async_engine(
        str(settings.database_url),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_overflow,
        pool_pre_ping=True,  # Verify connections before use
        echo=settings.is_development,  # SQL logging in development
    )

    # Create session factory
    _async_session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    logger.info("Database connection initialized")


async def close_database() -> None:
    """Close database connections.

    Called during application shutdown.
    Disposes of the engine and releases all connections.
    """
    global _engine, _async_session_factory

    if _engine is not None:
        logger.info("Closing database connections")
        await _engine.dispose()
        _engine = None
        _async_session_factory = None
        logger.info("Database connections closed")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session.

    Yields a session and ensures proper cleanup.
    Use as a dependency in FastAPI routes.

    Yields:
        AsyncSession for database operations

    Raises:
        RuntimeError: If database is not initialized
    """
    if _async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")

    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_health() -> tuple[bool, str | None]:
    """Check database connectivity.

    Returns:
        Tuple of (is_healthy, error_message)
    """
    if _engine is None:
        return False, "Database not initialized"

    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, None
    except Exception as e:
        logger.error("Database health check failed", error=str(e))
        return False, str(e)
