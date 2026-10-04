"""Admin authentication for the Model Management page.

Scope: ONLY routes under /api/v1/admin use anything in this module. No
existing route depends on it, so their behaviour is unchanged whether or not
admin auth is configured.

Configuration (environment):
    RUTH_ADMIN_USERNAME             admin login name
    RUTH_ADMIN_PASSWORD_HASH        bcrypt hash (scripts/make_admin_hash.py)
    RUTH_ADMIN_TRUSTED_PROXY_HOSTS  optional, comma-separated hostnames/IPs
                                    whose X-Real-IP header is trusted for the
                                    login rate limit (e.g. the nginx container)
    JWT_SECRET_KEY                  existing setting (RUTH_JWT_SECRET in the
                                    deploy .env); signs admin tokens

If the username or hash is missing/invalid, or the JWT secret is empty or a
known default, every admin route answers 503 "admin not configured". The
backend itself starts normally either way.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

ADMIN_ROLE = "admin"
TOKEN_AUDIENCE = "ruth-admin"
JWT_ALGORITHM = "HS256"
TOKEN_TTL = timedelta(hours=8)

# bcrypt only looks at the first 72 bytes; bcrypt>=5 raises on longer input.
BCRYPT_MAX_PASSWORD_BYTES = 72

# Secrets that must never sign admin tokens. Compared case-insensitively.
KNOWN_DEFAULT_SECRETS = frozenset(
    {
        "",
        "change_me_in_production",  # app.core.config default
        "change_me_in_production_use_strong_random_key",  # .env.example
        "changeme",
        "change_me",
        "change-me",
        "secret",
        "jwt_secret",
        "dev-secret",
        "development",
    }
)


# =============================================================================
# Configuration
# =============================================================================


class AdminAuthSettings(BaseSettings):
    """Admin-only settings, read from the environment (no .env file)."""

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    ruth_admin_username: str = ""
    ruth_admin_password_hash: str = ""
    ruth_admin_trusted_proxy_hosts: str = ""


@dataclass(frozen=True)
class AdminAuthConfig:
    """Resolved admin auth configuration.

    ``problem`` is None when admin login is usable; otherwise it says why not
    (logged, never returned to clients).
    """

    username: str
    password_hash: bytes
    jwt_secret: str
    trusted_proxy_hosts: tuple[str, ...]
    problem: str | None

    @property
    def configured(self) -> bool:
        return self.problem is None


def _hash_problem(password_hash: str) -> str | None:
    if not password_hash:
        return "RUTH_ADMIN_PASSWORD_HASH is not set"
    if len(password_hash) != 60 or password_hash[:4] not in ("$2a$", "$2b$", "$2y$"):
        # A hash mangled by shell/compose `$` interpolation lands here.
        return "RUTH_ADMIN_PASSWORD_HASH is not a bcrypt hash"
    try:
        bcrypt.checkpw(b"probe", password_hash.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return "RUTH_ADMIN_PASSWORD_HASH is not a valid bcrypt hash"
    return None


def build_admin_auth_config(
    settings: AdminAuthSettings, jwt_secret: str
) -> AdminAuthConfig:
    """Validate settings into an AdminAuthConfig. Never raises."""
    username = settings.ruth_admin_username.strip()
    password_hash = settings.ruth_admin_password_hash.strip()
    trusted = tuple(
        h.strip() for h in settings.ruth_admin_trusted_proxy_hosts.split(",") if h.strip()
    )

    problem: str | None
    if not username:
        problem = "RUTH_ADMIN_USERNAME is not set"
    elif jwt_secret.strip().lower() in KNOWN_DEFAULT_SECRETS:
        problem = "JWT secret is empty or a known default"
    else:
        problem = _hash_problem(password_hash)

    return AdminAuthConfig(
        username=username,
        password_hash=password_hash.encode("ascii", errors="replace"),
        jwt_secret=jwt_secret,
        trusted_proxy_hosts=trusted,
        problem=problem,
    )


@lru_cache
def get_admin_auth_config() -> AdminAuthConfig:
    """Process-wide admin auth config (resolved once, on first admin request).

    Sync on purpose: FastAPI runs sync dependencies in its threadpool, so the
    one-time bcrypt validation in _hash_problem never blocks the event loop.
    """
    config = build_admin_auth_config(AdminAuthSettings(), get_settings().jwt_secret_key)
    if config.configured:
        logger.info("Admin login enabled", trusted_proxy_hosts=list(config.trusted_proxy_hosts))
    else:
        logger.warning("Admin login disabled", reason=config.problem)
    return config


# =============================================================================
# Tokens
# =============================================================================


@dataclass(frozen=True)
class AdminPrincipal:
    username: str
    role: str
    expires_at: datetime


def issue_admin_token(
    config: AdminAuthConfig, now: datetime | None = None
) -> tuple[str, datetime]:
    """Return (token, expires_at) for the configured admin."""
    issued = now or datetime.now(timezone.utc)
    expires = issued + TOKEN_TTL
    payload = {
        "sub": config.username,
        "role": ADMIN_ROLE,
        "aud": TOKEN_AUDIENCE,
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
    }
    token = jwt.encode(payload, config.jwt_secret, algorithm=JWT_ALGORITHM)
    return token, datetime.fromtimestamp(payload["exp"], tz=timezone.utc)


def decode_admin_token(config: AdminAuthConfig, token: str) -> AdminPrincipal:
    """Validate an admin token. Raises jwt.InvalidTokenError (or a subclass)."""
    claims = jwt.decode(
        token,
        config.jwt_secret,
        algorithms=[JWT_ALGORITHM],
        audience=TOKEN_AUDIENCE,
        options={"require": ["sub", "role", "aud", "iat", "exp"]},
    )
    # A token minted for a previous admin username stops working when the
    # username changes.
    if claims["role"] != ADMIN_ROLE or not hmac.compare_digest(
        str(claims["sub"]).encode(), config.username.encode()
    ):
        raise jwt.InvalidTokenError("not an admin token for this deployment")
    return AdminPrincipal(
        username=config.username,
        role=ADMIN_ROLE,
        expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
    )


# =============================================================================
# Credentials
# =============================================================================


async def verify_admin_credentials(
    config: AdminAuthConfig, username: str, password: str
) -> bool:
    """Check username + password in constant time with respect to the username.

    The bcrypt check always runs, even for a wrong username or an over-long
    password, so response timing does not reveal which part was wrong.
    """
    username_ok = hmac.compare_digest(username.encode(), config.username.encode())
    password_bytes = password.encode("utf-8")
    too_long = len(password_bytes) > BCRYPT_MAX_PASSWORD_BYTES
    candidate = b"" if too_long else password_bytes
    password_ok = await asyncio.to_thread(bcrypt.checkpw, candidate, config.password_hash)
    return username_ok and password_ok and not too_long


# =============================================================================
# Login rate limiting
# =============================================================================


class LoginRateLimiter:
    """In-memory failed-login limiter, keyed by client IP.

    After ``max_failures`` failures inside ``window_seconds`` the key is locked
    until the oldest of those failures ages out. Attempts while locked are not
    evaluated and do not extend the lock. A success clears the key.

    Per-process state: correct for the backend's single uvicorn worker.
    """

    def __init__(
        self,
        max_failures: int = 5,
        window_seconds: float = 15 * 60,
        max_tracked_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.max_tracked_keys = max_tracked_keys
        self._clock = clock
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()

    def _prune(self, key: str, now: float) -> deque[float] | None:
        failures = self._failures.get(key)
        if failures is None:
            return None
        while failures and now - failures[0] >= self.window_seconds:
            failures.popleft()
        if not failures:
            del self._failures[key]
            return None
        return failures

    def retry_after(self, key: str) -> int | None:
        """Seconds until ``key`` may try again, or None if not locked."""
        now = self._clock()
        failures = self._prune(key, now)
        if failures is None or len(failures) < self.max_failures:
            return None
        return max(1, int(self.window_seconds - (now - failures[0])) + 1)

    def record_failure(self, key: str) -> None:
        now = self._clock()
        failures = self._prune(key, now)
        if failures is None:
            failures = deque()
            self._failures[key] = failures
        failures.append(now)
        self._failures.move_to_end(key)
        while len(self._failures) > self.max_tracked_keys:
            self._failures.popitem(last=False)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


_login_rate_limiter = LoginRateLimiter()


def get_login_rate_limiter() -> LoginRateLimiter:
    return _login_rate_limiter


# =============================================================================
# Client IP
# =============================================================================


class ClientIPResolver:
    """Client IP for rate limiting.

    Uses the TCP peer address, except when the peer is one of the trusted
    proxy hosts (the nginx frontend), in which case nginx's X-Real-IP is used.
    The backend port is also published on the host, so X-Real-IP from any
    other peer is ignored: it would be client-controlled.
    """

    def __init__(
        self,
        trusted_hosts: tuple[str, ...],
        cache_seconds: float = 60.0,
        miss_refresh_seconds: float = 5.0,
    ) -> None:
        self.trusted_hosts = trusted_hosts
        self.cache_seconds = cache_seconds
        # A peer outside the cached set re-resolves once the cache is this old,
        # so a recreated frontend container (new IP) is picked up within
        # seconds instead of after the full cache_seconds.
        self.miss_refresh_seconds = miss_refresh_seconds
        self._cached_ips: frozenset[str] = frozenset()
        self._cached_at: float | None = None

    async def _trusted_ips(self, max_age: float | None = None) -> frozenset[str]:
        now = time.monotonic()
        limit = self.cache_seconds if max_age is None else max_age
        if self._cached_at is not None and now - self._cached_at < limit:
            return self._cached_ips
        loop = asyncio.get_running_loop()
        ips: set[str] = set()
        for host in self.trusted_hosts:
            try:
                ips.add(str(ipaddress.ip_address(host)))
                continue
            except ValueError:
                pass
            try:
                for info in await loop.getaddrinfo(host, None):
                    ips.add(str(info[4][0]))
            except OSError:
                logger.debug("Trusted proxy host did not resolve", host=host)
        self._cached_ips = frozenset(ips)
        self._cached_at = now
        return self._cached_ips

    async def resolve(self, request: Request) -> str:
        peer = request.client.host if request.client else "unknown"
        if not self.trusted_hosts:
            return peer
        trusted = await self._trusted_ips()
        if peer not in trusted:
            trusted = await self._trusted_ips(max_age=self.miss_refresh_seconds)
        if peer not in trusted:
            return peer
        real_ip = request.headers.get("x-real-ip", "").strip()
        try:
            return str(ipaddress.ip_address(real_ip))
        except ValueError:
            return peer


@lru_cache
def get_client_ip_resolver() -> ClientIPResolver:
    return ClientIPResolver(get_admin_auth_config().trusted_proxy_hosts)


# =============================================================================
# Dependencies
# =============================================================================

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "unauthorized", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin_configured(
    config: Annotated[AdminAuthConfig, Depends(get_admin_auth_config)],
) -> AdminAuthConfig:
    """503 on every admin route until admin auth is configured."""
    if not config.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "admin_not_configured", "message": "admin not configured"},
        )
    return config


def require_admin(
    config: Annotated[AdminAuthConfig, Depends(require_admin_configured)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AdminPrincipal:
    """Valid admin bearer token, or 401."""
    if credentials is None:
        raise _unauthorized("missing bearer token")
    try:
        return decode_admin_token(config, credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("token expired")
    except jwt.InvalidTokenError:
        raise _unauthorized("invalid token")


AdminUser = Annotated[AdminPrincipal, Depends(require_admin)]
