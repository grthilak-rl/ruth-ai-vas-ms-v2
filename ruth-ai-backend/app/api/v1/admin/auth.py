"""POST /api/v1/admin/auth/login."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.admin_auth import (
    AdminAuthConfig,
    ClientIPResolver,
    LoginRateLimiter,
    get_client_ip_resolver,
    get_login_rate_limiter,
    issue_admin_token,
    require_admin_configured,
    verify_admin_credentials,
)
from app.core.logging import get_logger
from app.schemas.admin import AdminLoginRequest, AdminLoginResponse

router = APIRouter(prefix="/auth")
logger = get_logger(__name__)


@router.post(
    "/login",
    response_model=AdminLoginResponse,
    summary="Admin login",
    description=(
        "Exchange the admin username and password for an 8-hour bearer token. "
        "5 failed attempts per client IP within 15 minutes returns 429."
    ),
)
async def admin_login(
    body: AdminLoginRequest,
    request: Request,
    config: Annotated[AdminAuthConfig, Depends(require_admin_configured)],
    limiter: Annotated[LoginRateLimiter, Depends(get_login_rate_limiter)],
    ip_resolver: Annotated[ClientIPResolver, Depends(get_client_ip_resolver)],
) -> AdminLoginResponse:
    client_ip = await ip_resolver.resolve(request)

    retry_after = limiter.retry_after(client_ip)
    if retry_after is not None:
        logger.warning("Admin login rate limited", client_ip=client_ip, retry_after=retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "too_many_attempts", "message": "too many failed login attempts"},
            headers={"Retry-After": str(retry_after)},
        )

    if not await verify_admin_credentials(config, body.username, body.password):
        limiter.record_failure(client_ip)
        # Never log the password, and log only whether the username matched:
        # people sometimes type their password into the username field.
        logger.warning(
            "Admin login failed",
            client_ip=client_ip,
            username_matches=body.username == config.username,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_credentials", "message": "invalid credentials"},
        )

    limiter.reset(client_ip)
    token, expires_at = issue_admin_token(config)
    logger.info("Admin login succeeded", client_ip=client_ip, username=config.username)
    return AdminLoginResponse(
        access_token=token,
        expires_at=expires_at,
        username=config.username,
    )
