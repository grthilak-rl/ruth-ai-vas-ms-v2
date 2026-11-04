"""Report branding API (admin protected_router): Settings -> Report branding.

- GET    /admin/report-branding        customer name, whether a logo is set
- PUT    /admin/report-branding        set the customer name
- PUT    /admin/report-branding/logo   upload the logo (raw PNG/JPEG body, ≤ 1 MB)
- GET    /admin/report-branding/logo   the stored logo, for the preview
- DELETE /admin/report-branding/logo   remove it

The logo is sent as the request body rather than a multipart form: one
file, no form fields, and no extra dependency. It is validated and
re-encoded before anything is written.
"""

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.admin_auth import AdminUser
from app.core.logging import get_logger
from app.deps import DBSession
from app.models.app_setting import REPORT_BRANDING_KEY, AppSetting
from app.schemas.customer_report import ReportBrandingIn, ReportBrandingOut
from app.services.report.branding import (
    MAX_LOGO_BYTES,
    LogoError,
    get_branding,
    prepare_logo,
    remove_logos,
    save_branding,
    store_logo,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/report-branding", tags=["Admin"])


async def _out(db) -> ReportBrandingOut:
    branding = await get_branding(db)
    row = (
        await db.execute(select(AppSetting).where(AppSetting.key == REPORT_BRANDING_KEY))
    ).scalars().first()
    return ReportBrandingOut(
        customer_name=branding.customer_name,
        has_logo=branding.logo_file() is not None,
        updated_by=row.updated_by if row else None,
        updated_at=row.updated_at if row else None,
    )


@router.get("", response_model=ReportBrandingOut, summary="Report branding")
async def read_branding(db: DBSession, _admin: AdminUser) -> ReportBrandingOut:
    return await _out(db)


@router.put("", response_model=ReportBrandingOut, summary="Set the customer name")
async def update_branding(body: ReportBrandingIn, db: DBSession, admin: AdminUser) -> ReportBrandingOut:
    branding = await get_branding(db)
    branding.customer_name = (body.customer_name or "").strip() or None
    await save_branding(db, branding, admin.username)
    logger.info("Report branding updated", customer_name=branding.customer_name, by=admin.username)
    return await _out(db)


@router.put("/logo", response_model=ReportBrandingOut, summary="Upload the customer logo")
async def upload_logo(request: Request, db: DBSession, admin: AdminUser) -> ReportBrandingOut:
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_LOGO_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={"error": "logo_too_large", "message": "The logo must be 1 MB or smaller."},
            )
    try:
        png = await run_in_threadpool(prepare_logo, bytes(data))
    except LogoError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_logo", "message": str(e)},
        ) from e
    name = await run_in_threadpool(store_logo, png)
    branding = await get_branding(db)
    branding.logo_file_name = name
    await save_branding(db, branding, admin.username)
    logger.info("Report logo uploaded", bytes=len(png), by=admin.username)
    return await _out(db)


@router.get("/logo", summary="The customer logo")
async def read_logo(db: DBSession, _admin: AdminUser) -> FileResponse:
    path = (await get_branding(db)).logo_file()
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "no_logo", "message": "no logo is set"},
        )
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.delete("/logo", response_model=ReportBrandingOut, summary="Remove the customer logo")
async def delete_logo(db: DBSession, admin: AdminUser) -> ReportBrandingOut:
    branding = await get_branding(db)
    branding.logo_file_name = None
    await save_branding(db, branding, admin.username)
    await run_in_threadpool(remove_logos)
    logger.info("Report logo removed", by=admin.username)
    return await _out(db)
