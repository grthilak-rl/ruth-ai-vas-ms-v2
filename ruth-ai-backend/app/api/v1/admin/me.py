"""GET /api/v1/admin/me (protected; mounted on the admin protected_router)."""

from fastapi import APIRouter

from app.core.admin_auth import AdminUser
from app.schemas.admin import AdminMeResponse

router = APIRouter()


@router.get(
    "/me",
    response_model=AdminMeResponse,
    summary="Current admin",
    description="Returns the admin identified by the bearer token.",
)
async def admin_me(admin: AdminUser) -> AdminMeResponse:
    return AdminMeResponse(
        username=admin.username,
        role=admin.role,
        expires_at=admin.expires_at,
    )
