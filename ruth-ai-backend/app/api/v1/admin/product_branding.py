"""Product branding API (admin protected_router): Settings -> System -> Branding.

- GET    /admin/product-branding                                  all profiles, which is active
- POST   /admin/product-branding/profiles                         add a profile
- PUT    /admin/product-branding/profiles/{id}                    edit its names, accent, report note
- DELETE /admin/product-branding/profiles/{id}                    delete it (not the active one)
- POST   /admin/product-branding/profiles/{id}/activate           make it the active brand
- PUT    /admin/product-branding/profiles/{id}/images/{slot}      upload an image (raw PNG/JPEG body, ≤ 1 MB)
- GET    /admin/product-branding/profiles/{id}/images/{slot}      the image, for the preview
- DELETE /admin/product-branding/profiles/{id}/images/{slot}      remove it

Slots: logo_light, logo_dark, icon. Uploads are validated and re-encoded
as PNG before anything is written (as for the report logo); SVG is not
accepted. What anyone may read without signing in is in api/v1/branding.py.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.core.admin_auth import AdminUser
from app.core.logging import get_logger
from app.deps import DBSession
from app.services.product_branding import (
    SLOTS,
    BrandFields,
    BrandingError,
    BrandProfile,
    ProductBranding,
    activate,
    add_profile,
    delete_image_file,
    image_path,
    image_version,
    load_for_edit,
    prepare_image,
    remove_profile,
    require_profile,
    save_branding,
    store_image,
    update_profile,
    updated_meta,
)
from app.services.report.branding import MAX_LOGO_BYTES, LogoError

logger = get_logger(__name__)

router = APIRouter(prefix="/product-branding", tags=["Admin"])

SlotParam = Literal["logo_light", "logo_dark", "icon"]


class ProfileOut(BaseModel):
    id: str
    name: str
    product_name: str
    short_name: str | None
    assistant_name: str | None
    accent: str | None
    report_note: str | None
    #: slot -> version string when the image is set, else None.
    images: dict[str, str | None]
    builtin_images: list[str]
    active: bool


class ProductBrandingOut(BaseModel):
    active_id: str
    profiles: list[ProfileOut]
    updated_by: str | None = None
    updated_at: datetime | None = None


def _profile_out(p: BrandProfile, active_id: str) -> ProfileOut:
    return ProfileOut(
        id=p.id,
        name=p.name,
        product_name=p.product_name,
        short_name=p.short_name,
        assistant_name=p.assistant_name,
        accent=p.accent,
        report_note=p.report_note,
        images={slot: image_version(p, slot) for slot in SLOTS},
        builtin_images=[s for s in SLOTS if (p.images.get(s) or "").startswith("builtin-")],
        active=p.id == active_id,
    )


async def _out(db, branding: ProductBranding) -> ProductBrandingOut:
    by, at = await updated_meta(db)
    return ProductBrandingOut(
        active_id=branding.active_id,
        profiles=[_profile_out(p, branding.active_id) for p in branding.profiles],
        updated_by=by,
        updated_at=at,
    )


def _not_found(profile_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "no_profile", "message": f"no brand profile {profile_id}"},
    )


def _conflict(e: BrandingError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"error": "branding_conflict", "message": str(e)},
    )


async def _save(db, branding: ProductBranding, by: str) -> ProductBrandingOut:
    try:
        await save_branding(db, branding, by)
    except BrandingError as e:
        raise _conflict(e) from e
    return await _out(db, branding)


@router.get("", response_model=ProductBrandingOut, summary="Product brand profiles")
async def read_product_branding(db: DBSession, _admin: AdminUser) -> ProductBrandingOut:
    return await _out(db, await load_for_edit(db))


@router.post(
    "/profiles",
    response_model=ProductBrandingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a brand profile",
)
async def create_profile(body: BrandFields, db: DBSession, admin: AdminUser) -> ProductBrandingOut:
    branding = await load_for_edit(db)
    try:
        profile = add_profile(branding, body)
    except BrandingError as e:
        raise _conflict(e) from e
    logger.info("Brand profile added", profile=profile.id, name=profile.name, by=admin.username)
    return await _save(db, branding, admin.username)


@router.put("/profiles/{profile_id}", response_model=ProductBrandingOut, summary="Edit a brand profile")
async def edit_profile(
    profile_id: str, body: BrandFields, db: DBSession, admin: AdminUser
) -> ProductBrandingOut:
    branding = await load_for_edit(db)
    try:
        update_profile(branding, profile_id, body)
    except LookupError as e:
        raise _not_found(profile_id) from e
    logger.info("Brand profile edited", profile=profile_id, by=admin.username)
    return await _save(db, branding, admin.username)


@router.delete("/profiles/{profile_id}", response_model=ProductBrandingOut, summary="Delete a brand profile")
async def delete_profile(profile_id: str, db: DBSession, admin: AdminUser) -> ProductBrandingOut:
    branding = await load_for_edit(db)
    try:
        removed = remove_profile(branding, profile_id)
    except LookupError as e:
        raise _not_found(profile_id) from e
    except BrandingError as e:
        raise _conflict(e) from e
    out = await _save(db, branding, admin.username)
    for name in removed.images.values():
        await run_in_threadpool(delete_image_file, name)
    logger.info("Brand profile deleted", profile=profile_id, by=admin.username)
    return out


@router.post(
    "/profiles/{profile_id}/activate",
    response_model=ProductBrandingOut,
    summary="Make a profile the active brand",
)
async def activate_profile(profile_id: str, db: DBSession, admin: AdminUser) -> ProductBrandingOut:
    branding = await load_for_edit(db)
    previous = branding.active_id
    try:
        profile = activate(branding, profile_id)
    except LookupError as e:
        raise _not_found(profile_id) from e
    logger.info(
        "Product brand switched",
        previous=previous,
        active=profile.id,
        product_name=profile.product_name,
        by=admin.username,
    )
    return await _save(db, branding, admin.username)


@router.put(
    "/profiles/{profile_id}/images/{slot}",
    response_model=ProductBrandingOut,
    summary="Upload a brand image",
)
async def upload_image(
    profile_id: str, slot: SlotParam, request: Request, db: DBSession, admin: AdminUser
) -> ProductBrandingOut:
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_LOGO_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={"error": "image_too_large", "message": "The image must be 1 MB or smaller."},
            )
    branding = await load_for_edit(db)
    try:
        profile = require_profile(branding, profile_id)
    except LookupError as e:
        raise _not_found(profile_id) from e
    try:
        png = await run_in_threadpool(prepare_image, slot, bytes(data))
    except LogoError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_image", "message": str(e)},
        ) from e
    name = await run_in_threadpool(store_image, profile_id, slot, png)
    old = profile.images.get(slot)
    profile.images[slot] = name
    out = await _save(db, branding, admin.username)
    await run_in_threadpool(delete_image_file, old)
    logger.info("Brand image uploaded", profile=profile_id, slot=slot, bytes=len(png), by=admin.username)
    return out


@router.get("/profiles/{profile_id}/images/{slot}", summary="A brand image, for the preview")
async def read_image(profile_id: str, slot: SlotParam, db: DBSession, _admin: AdminUser) -> FileResponse:
    branding = await load_for_edit(db)
    try:
        profile = require_profile(branding, profile_id)
    except LookupError as e:
        raise _not_found(profile_id) from e
    path = image_path(profile, slot)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "no_image", "message": f"no {slot} is set"},
        )
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.delete(
    "/profiles/{profile_id}/images/{slot}",
    response_model=ProductBrandingOut,
    summary="Remove a brand image",
)
async def delete_image(profile_id: str, slot: SlotParam, db: DBSession, admin: AdminUser) -> ProductBrandingOut:
    branding = await load_for_edit(db)
    try:
        profile = require_profile(branding, profile_id)
    except LookupError as e:
        raise _not_found(profile_id) from e
    old = profile.images.get(slot)
    profile.images[slot] = None
    out = await _save(db, branding, admin.username)
    await run_in_threadpool(delete_image_file, old)
    logger.info("Brand image removed", profile=profile_id, slot=slot, by=admin.username)
    return out
