"""Footage retention, as VAS has it: shown in Settings -> System.

- GET /api/v1/storage/footage-retention          open: what VAS will delete
- PUT /api/v1/admin/footage-retention            admin: change the switch

VAS is the single source of truth: nothing is stored in Ruth. Every read
asks VAS (storage_config), every change is forwarded to it. Footage
(recordings, snapshots, bookmarks) is deleted only by VAS's retention
cleanup, and only while ``cleanup_enabled`` is on and not paused; the
default is off.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.admin_auth import AdminUser
from app.core.logging import get_logger
from app.deps import VASClientDep
from app.integrations.vas import VASError

logger = get_logger(__name__)

router = APIRouter(tags=["Storage"])
admin_router = APIRouter(tags=["Admin"])


class FootageRetention(BaseModel):
    #: "off", "paused" or "on".
    footage_deletion: str
    cleanup_enabled: bool
    retention_paused: bool
    #: Only meaningful while deletion is on.
    hot_retention_days: int | None = None
    hot_retention_days_set: bool = False
    snapshot_retention_days: int | None = None
    bookmark_retention_days: int | None = None
    disk_alert_enabled: bool | None = None
    disk_usage_percent: float | None = None
    disk_free_bytes: int | None = None
    #: "ok", "warning", "critical", or None when the alert is off.
    disk_alert_level: str | None = None
    disk_warning_threshold: int | None = None
    disk_critical_threshold: int | None = None
    updated_at: str | None = None


class FootageRetentionUpdate(BaseModel):
    cleanup_enabled: bool | None = None
    retention_paused: bool | None = None
    hot_retention_days: int | None = Field(default=None, ge=1, le=365)


def _view(config: dict) -> FootageRetention:
    return FootageRetention(
        footage_deletion=config.get("footage_deletion", "off"),
        cleanup_enabled=bool(config.get("cleanup_enabled")),
        retention_paused=bool(config.get("retention_paused")),
        **{k: config.get(k) for k in (
            "hot_retention_days", "snapshot_retention_days", "bookmark_retention_days",
            "disk_alert_enabled", "disk_usage_percent", "disk_free_bytes", "disk_alert_level",
            "disk_warning_threshold", "disk_critical_threshold", "updated_at",
        )},
        hot_retention_days_set=bool(config.get("hot_retention_days_set")),
    )


def _unavailable(e: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"error": "vas_unavailable", "message": f"Could not reach VAS storage config: {e}"},
    )


@router.get("/storage/footage-retention", response_model=FootageRetention)
async def get_footage_retention(vas: VASClientDep) -> FootageRetention:
    try:
        return _view(await vas.get_storage_config())
    except VASError as e:
        raise _unavailable(e) from e


@admin_router.put("/footage-retention", response_model=FootageRetention)
async def update_footage_retention(
    body: FootageRetentionUpdate, vas: VASClientDep, admin: AdminUser
) -> FootageRetention:
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "nothing_to_change", "message": "No change requested"},
        )
    try:
        config = await vas.update_storage_config(updates)
    except VASError as e:
        # VAS refuses to turn deletion on without explicit days (400).
        if getattr(e, "status_code", None) == 400:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "rejected_by_vas", "message": str(e)},
            ) from e
        raise _unavailable(e) from e
    logger.warning(
        "Footage retention changed",
        changes=updates,
        footage_deletion=config.get("footage_deletion"),
        by=admin.username,
    )
    return _view(config)
