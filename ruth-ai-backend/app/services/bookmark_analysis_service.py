"""Bookmark analysis service.

Owns the lifecycle of bookmark_analyses rows: submit (pending) →
worker picks it up (running) → terminal (completed / failed).

Phase D.1: worker is a placeholder that sleeps 3s and writes a stub
summary so the submit/poll/list loop is wired end-to-end. Phase D.2
replaces ``_run_stub_analysis`` with real model dispatch.

Workers run via FastAPI's BackgroundTasks. They open their own DB
session via the session factory rather than borrowing the request's
session, because BackgroundTasks fire after the request returns and
its session has been closed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.models import BookmarkAnalysis, BookmarkAnalysisState
from app.schemas.bookmark_analysis import BookmarkAnalysisSubmitRequest

logger = get_logger(__name__)

# How long the D.1 placeholder pretends to work. Long enough for an
# operator to submit + immediately query and see "running", short
# enough not to be annoying when running tests.
STUB_ANALYSIS_DURATION_SECONDS = 3.0


class BookmarkAnalysisService:
    """Manages bookmark_analyses rows.

    Service is intentionally thin: persistence + state transitions.
    Real model dispatch lives in ``_run_stub_analysis`` for D.1 and
    will be replaced in D.2.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the service.

        Args:
            db: A request-scoped DB session. Used for the submit/get/list
                operations. The worker (run_analysis) opens its own
                session via the global factory.
        """
        self._db = db

    # -------------------------------------------------------------------------
    # CRUD-shaped operations (request-scoped session)
    # -------------------------------------------------------------------------

    async def submit(
        self,
        request: BookmarkAnalysisSubmitRequest,
    ) -> BookmarkAnalysis:
        """Persist a new analysis row in state=PENDING.

        Returns the created row with all server-generated columns
        populated (id, created_at, state). The caller is responsible
        for scheduling ``run_analysis(analysis.id)`` via FastAPI
        BackgroundTasks after this returns.
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

    # -------------------------------------------------------------------------
    # Worker (background task)
    # -------------------------------------------------------------------------


async def run_analysis(analysis_id: UUID) -> None:
    """Background worker entry point.

    Loads the analysis row, transitions to RUNNING, calls the
    analysis function, transitions to terminal state. Any exception
    is caught, logged at warning, and persisted as state=FAILED with
    error_message — the worker never crashes the BackgroundTasks
    runner.

    Opens its own DB session via the global factory because
    BackgroundTasks fires after the request's session has closed.
    """
    factory = get_session_factory()
    if factory is None:
        logger.error(
            "Cannot run bookmark analysis — DB session factory not initialized",
            analysis_id=str(analysis_id),
        )
        return

    async with factory() as db:
        analysis = await _load_for_worker(db, analysis_id)
        if analysis is None:
            logger.warning(
                "Bookmark analysis row missing when worker started",
                analysis_id=str(analysis_id),
            )
            return

        # Defensive: skip rows that aren't actually pending. Could happen if
        # the worker is somehow re-fired (it isn't today, but the guard is
        # cheap insurance for future retry/cancel logic).
        if analysis.state != BookmarkAnalysisState.PENDING:
            logger.info(
                "Skipping bookmark analysis worker — row not in pending state",
                analysis_id=str(analysis_id),
                state=analysis.state.value,
            )
            return

        # Transition PENDING -> RUNNING in its own transaction so the
        # state flip is visible to pollers immediately, even if the
        # analysis itself is slow.
        analysis.state = BookmarkAnalysisState.RUNNING
        analysis.started_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(analysis)

        logger.info(
            "Bookmark analysis running",
            analysis_id=str(analysis_id),
            model_id=analysis.model_id,
        )

        try:
            summary = await _run_stub_analysis(analysis)
        except Exception as e:
            analysis.state = BookmarkAnalysisState.FAILED
            analysis.error_message = str(e)[:2000]
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.warning(
                "Bookmark analysis failed",
                analysis_id=str(analysis_id),
                error=str(e),
                error_type=type(e).__name__,
            )
            return

        analysis.state = BookmarkAnalysisState.COMPLETED
        analysis.summary = summary
        analysis.completed_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(
            "Bookmark analysis completed",
            analysis_id=str(analysis_id),
            model_id=analysis.model_id,
        )


async def _load_for_worker(
    db: AsyncSession,
    analysis_id: UUID,
) -> BookmarkAnalysis | None:
    """Fetch a row for the worker. Same shape as service.get."""
    stmt = select(BookmarkAnalysis).where(BookmarkAnalysis.id == analysis_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _run_stub_analysis(analysis: BookmarkAnalysis) -> dict[str, Any]:
    """Phase D.1 placeholder.

    Sleeps for STUB_ANALYSIS_DURATION_SECONDS to simulate work, then
    returns a fixed shape. Phase D.2 replaces this with real model
    dispatch (download bookmark video from VAS, decode frames, run
    inference, aggregate).
    """
    await asyncio.sleep(STUB_ANALYSIS_DURATION_SECONDS)
    return {
        "placeholder": True,
        "model_id": analysis.model_id,
        "model_version": analysis.model_version,
        "note": "D.1 stub — real analysis lands in D.2.",
        "parameters_echoed": analysis.parameters,
    }
