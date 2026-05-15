"""Bookmark analysis API endpoints.

POST   /api/v1/bookmark-analyses                          submit
GET    /api/v1/bookmark-analyses                          list recent
GET    /api/v1/bookmark-analyses/{id}                     get one
GET    /api/v1/bookmarks/{vas_bookmark_id}/analyses       list for bookmark

Phase D.1 wires the submit/poll/list loop end-to-end with a
placeholder worker. The worker runs via FastAPI BackgroundTasks —
no external job queue.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.core.logging import get_logger
from app.deps import DBSession
from app.schemas import ErrorResponse
from app.schemas.bookmark_analysis import (
    BookmarkAnalysisListItem,
    BookmarkAnalysisListResponse,
    BookmarkAnalysisResponse,
    BookmarkAnalysisSubmitRequest,
)
from app.services.bookmark_analysis_service import (
    BookmarkAnalysisService,
    run_analysis,
)

logger = get_logger(__name__)

# Two prefixes: the /bookmark-analyses collection and the per-bookmark
# subresource. Both live in this file so the routing model is obvious.
router = APIRouter(prefix="/bookmark-analyses", tags=["Bookmark Analyses"])
bookmark_subresource_router = APIRouter(prefix="/bookmarks", tags=["Bookmark Analyses"])


@router.post(
    "",
    response_model=BookmarkAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a bookmark analysis",
    description=(
        "Create a new async analysis job against a VAS bookmark. Returns the "
        "new record immediately in state=pending. The worker runs in the "
        "background; poll GET /api/v1/bookmark-analyses/{id} to observe state "
        "transitions."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request payload"},
    },
)
async def submit_analysis(
    request: BookmarkAnalysisSubmitRequest,
    db: DBSession,
    background_tasks: BackgroundTasks,
) -> BookmarkAnalysisResponse:
    service = BookmarkAnalysisService(db=db)
    analysis = await service.submit(request)
    # Schedule the worker only after the row commits. BackgroundTasks
    # fires after the response is sent, so the caller's poll for state
    # always finds the row at minimum in PENDING.
    background_tasks.add_task(run_analysis, analysis.id)
    return BookmarkAnalysisResponse.model_validate(analysis)


@router.get(
    "/{analysis_id}",
    response_model=BookmarkAnalysisResponse,
    summary="Get a bookmark analysis by id",
    responses={
        404: {"model": ErrorResponse, "description": "Analysis not found"},
    },
)
async def get_analysis(
    analysis_id: UUID,
    db: DBSession,
) -> BookmarkAnalysisResponse:
    service = BookmarkAnalysisService(db=db)
    analysis = await service.get(analysis_id)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "analysis_not_found",
                "message": f"Bookmark analysis {analysis_id} not found",
            },
        )
    return BookmarkAnalysisResponse.model_validate(analysis)


@router.get(
    "",
    response_model=BookmarkAnalysisListResponse,
    summary="List recent bookmark analyses",
    description="Returns the most recent analyses across all bookmarks, newest first.",
)
async def list_recent_analyses(
    db: DBSession,
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
) -> BookmarkAnalysisListResponse:
    service = BookmarkAnalysisService(db=db)
    rows = await service.list_recent(limit=limit)
    items = [BookmarkAnalysisListItem.model_validate(r) for r in rows]
    return BookmarkAnalysisListResponse(items=items, total=len(items))


@bookmark_subresource_router.get(
    "/{vas_bookmark_id}/analyses",
    response_model=BookmarkAnalysisListResponse,
    summary="List analyses for a specific bookmark",
    description="Returns all analyses for one VAS bookmark, newest first.",
)
async def list_analyses_for_bookmark(
    vas_bookmark_id: str,
    db: DBSession,
) -> BookmarkAnalysisListResponse:
    service = BookmarkAnalysisService(db=db)
    rows = await service.list_for_bookmark(vas_bookmark_id)
    items = [BookmarkAnalysisListItem.model_validate(r) for r in rows]
    return BookmarkAnalysisListResponse(items=items, total=len(items))
