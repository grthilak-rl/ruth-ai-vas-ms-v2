"""Database dependency injection for FastAPI routes.

Provides:
- Database session dependency for route injection
- Transaction-safe session management
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions.

    Provides an async database session that:
    - Auto-commits on successful request completion
    - Auto-rolls back on exceptions
    - Properly closes the session after use

    Yields:
        AsyncSession for database operations
    """
    async for session in get_db_session():
        yield session


# Type alias for dependency injection
DBSession = Annotated[AsyncSession, Depends(get_db)]
