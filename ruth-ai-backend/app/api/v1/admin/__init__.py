"""Admin API (/api/v1/admin) for the Model Management page.

Everything here is admin-only via require_admin, except POST /admin/auth/login.
Protected endpoints go on ``protected_router``; nothing else in the app
depends on this package.
"""

from fastapi import APIRouter, Depends

from app.api.v1.admin import auth, me, model_store
from app.core.admin_auth import require_admin

router = APIRouter(prefix="/admin", tags=["Admin"])

# Unauthenticated: login only.
router.include_router(auth.router)

# Everything else requires a valid admin token.
protected_router = APIRouter(dependencies=[Depends(require_admin)])
protected_router.include_router(me.router)
protected_router.include_router(model_store.router)
router.include_router(protected_router)

__all__ = ["router"]
