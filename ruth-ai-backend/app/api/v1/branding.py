"""The active product brand, readable without signing in.

- GET /branding               product name, accent, image URLs (no-cache)
- GET /branding/asset/{slot}  the active profile's image: logo_light,
                              logo_dark or icon

The sign-in page and the favicon need these before anyone signs in, so they
are open. They expose the active brand only: no other profiles, no profile
ids, no audit fields. Image URLs carry a version (``?v=``) that changes with
the image, so a request that names the current version may be cached for a
year; anything else is served ``no-cache`` (``index.html`` links the bare
icon URL as the favicon, which then follows a brand switch on reload).
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse

from app.deps import DBSession
from app.services.product_branding import get_active, image_path, image_version, public_view

router = APIRouter(prefix="/branding", tags=["Branding"])

_NOSNIFF = {"X-Content-Type-Options": "nosniff"}


@router.get("", summary="The active product brand")
async def read_active_brand(db: DBSession) -> JSONResponse:
    profile = await get_active(db)
    return JSONResponse(public_view(profile), headers={"Cache-Control": "no-cache", **_NOSNIFF})


@router.get("/asset/{slot}", summary="An image of the active product brand")
async def read_brand_asset(
    slot: Literal["logo_light", "logo_dark", "icon"],
    db: DBSession,
    v: str | None = Query(default=None, max_length=32),
) -> FileResponse:
    profile = await get_active(db)
    path = image_path(profile, slot)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "no_image", "message": f"the active brand has no {slot}"},
        )
    current = image_version(profile, slot)
    cache = "public, max-age=31536000, immutable" if v and v == current else "no-cache"
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": cache, **_NOSNIFF})
