"""Database dependency injection for FastAPI routes.

Provides:
- Database session dependency for route injection
- Transaction-safe session management
- The request's project scope (project view mode, app/core/project_scope.py)
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.project_scope import (
    HEADER,
    QUERY_PARAM,
    ProjectScope,
    UnknownProjectError,
    resolve_scope,
    scope_session,
)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions.

    Provides an async database session that:
    - Auto-commits on successful request completion
    - Auto-rolls back on exceptions
    - Properly closes the session after use
    - Is scoped to the project this request reads (see project_scope); the
      resolved scope is also left on ``request.state.project_scope``

    Yields:
        AsyncSession for database operations
    """
    async for session in get_db_session():
        ref = request.headers.get(HEADER) or request.query_params.get(QUERY_PARAM)
        try:
            scope = await resolve_scope(session, request.url.path, ref)
        except UnknownProjectError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "project_not_found", "message": f"No project {e.ref!r}"},
            ) from e
        if scope.filtered:
            scope_session(session, scope.project_id)
        request.state.project_scope = scope
        yield session


# Type alias for dependency injection
DBSession = Annotated[AsyncSession, Depends(get_db)]


async def get_project_scope(request: Request, _db: DBSession) -> ProjectScope:
    """The project this request reads. Depends on get_db, which resolves it."""
    return request.state.project_scope


ProjectScopeDep = Annotated[ProjectScope, Depends(get_project_scope)]
