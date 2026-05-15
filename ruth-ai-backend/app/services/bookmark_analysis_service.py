"""Bookmark analysis service.

Owns the lifecycle of bookmark_analyses rows: submit (pending) →
worker picks it up (running) → terminal (completed / failed).

The request-scoped service class (this module) handles CRUD-shaped
operations. The async worker — download bookmark video from VAS,
extract frames, dispatch inference, aggregate — lives in
``bookmark_analysis_worker`` so this module stays small and the
worker's heavy imports (cv2) are only loaded when needed.

The worker entry point is re-exported as ``run_analysis`` for
backwards compatibility with the API layer.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import BookmarkAnalysis, BookmarkAnalysisState
from app.schemas.bookmark_analysis import BookmarkAnalysisSubmitRequest
from app.services.bookmark_analysis_worker import run_analysis

__all__ = ["BookmarkAnalysisService", "run_analysis"]

logger = get_logger(__name__)


class BookmarkAnalysisService:
    """CRUD-shaped operations against bookmark_analyses.

    Construct per request with the request's DB session. The worker
    opens its own session — see ``bookmark_analysis_worker.run_analysis``.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def submit(
        self,
        request: BookmarkAnalysisSubmitRequest,
    ) -> BookmarkAnalysis:
        """Persist a new analysis row in state=PENDING.

        Returns the created row with all server-generated columns
        populated. The caller is responsible for scheduling
        ``run_analysis(analysis.id)`` via FastAPI BackgroundTasks
        after this returns.
        """
        analysis = BookmarkAnalysis(
            vas_bookmark_id=request.vas_bookmark_id,
            model_id=request.model_id,
            model_version=request.model_version,
            parameters=request.parameters,
            state=BookmarkAnalysisState.PENDING,
        )
        self._db.add(analysis)
        await self._db.commit()
        await self._db.refresh(analysis)
        logger.info(
            "Bookmark analysis submitted",
            analysis_id=str(analysis.id),
            vas_bookmark_id=analysis.vas_bookmark_id,
            model_id=analysis.model_id,
        )
        return analysis

    async def get(self, analysis_id: UUID) -> BookmarkAnalysis | None:
        """Look up an analysis by id. Returns None if not found."""
        stmt = select(BookmarkAnalysis).where(BookmarkAnalysis.id == analysis_id)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_bookmark(
        self,
        vas_bookmark_id: str,
    ) -> list[BookmarkAnalysis]:
        """Return analyses for one bookmark, newest first."""
        stmt = (
            select(BookmarkAnalysis)
            .where(BookmarkAnalysis.vas_bookmark_id == vas_bookmark_id)
            .order_by(BookmarkAnalysis.created_at.desc())
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def list_recent(self, limit: int = 50) -> list[BookmarkAnalysis]:
        """Return the most recent N analyses across all bookmarks."""
        stmt = (
            select(BookmarkAnalysis)
            .order_by(BookmarkAnalysis.created_at.desc())
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())
