"""Tests for admin login (/api/v1/admin) and its isolation from existing routes.

No database or external service is needed: admin config, rate limiter, client
IP resolver and (for the existing-route checks) the DB session are overridden.
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.admin_auth import (
    JWT_ALGORITHM,
    TOKEN_AUDIENCE,
    TOKEN_TTL,
    AdminAuthConfig,
    AdminAuthSettings,
    ClientIPResolver,
    LoginRateLimiter,
    build_admin_auth_config,
    get_admin_auth_config,
    get_client_ip_resolver,
    get_login_rate_limiter,
    issue_admin_token,
)
from app.deps.db import get_db
from app.main import create_application
from tests.unit.conftest import MockAsyncSession

USERNAME = "admin"
PASSWORD = "correct horse battery staple"
SECRET = "s" * 64
LOGIN = "/api/v1/admin/auth/login"
ME = "/api/v1/admin/me"

# rounds=4: the bcrypt minimum, so the suite stays fast.
PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()


def make_config(
    username: str = USERNAME,
    password_hash: str = PASSWORD_HASH,
    secret: str = SECRET,
) -> AdminAuthConfig:
    return build_admin_auth_config(
        AdminAuthSettings(
            ruth_admin_username=username,
            ruth_admin_password_hash=password_hash,
        ),
        secret,
    )


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def config() -> AdminAuthConfig:
    return make_config()


@pytest.fixture
def app(config, clock):
    application = create_application()
    limiter = LoginRateLimiter(clock=clock)
    application.dependency_overrides[get_admin_auth_config] = lambda: config
    application.dependency_overrides[get_login_rate_limiter] = lambda: limiter
    application.dependency_overrides[get_client_ip_resolver] = lambda: ClientIPResolver(())
    return application


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def login(client: AsyncClient, username: str = USERNAME, password: str = PASSWORD, **kw):
    return await client.post(LOGIN, json={"username": username, "password": password}, **kw)


# =============================================================================
# Login
# =============================================================================


async def test_login_success_returns_8h_admin_token(client):
    response = await login(client)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["username"] == USERNAME
    claims = jwt.decode(
        body["access_token"], SECRET, algorithms=[JWT_ALGORITHM], audience=TOKEN_AUDIENCE
    )
    assert claims["sub"] == USERNAME
    assert claims["role"] == "admin"
    assert claims["exp"] - claims["iat"] == int(TOKEN_TTL.total_seconds())

    me = await client.get(ME, headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["username"] == USERNAME
    assert me.json()["role"] == "admin"


async def test_login_failures_are_generic(client):
    wrong_password = await login(client, password="nope")
    wrong_username = await login(client, username="root")
    too_long = await login(client, password="x" * 100)

    for response in (wrong_password, wrong_username, too_long):
        assert response.status_code == 401
    # Same body whichever part was wrong.
    assert wrong_password.json() == wrong_username.json() == too_long.json()
    assert wrong_password.json()["detail"]["message"] == "invalid credentials"


async def test_login_validates_body(client):
    response = await client.post(LOGIN, json={"username": "", "password": ""})
    # The app's validation_error_handler maps request validation to 400.
    assert response.status_code == 400


# =============================================================================
# Rate limit
# =============================================================================


async def test_rate_limit_after_five_failures(client, clock):
    for _ in range(5):
        assert (await login(client, password="nope")).status_code == 401

    locked = await login(client)  # correct password, still refused
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0

    clock.now += 15 * 60
    assert (await login(client)).status_code == 200


async def test_success_resets_failure_count(client):
    for _ in range(4):
        await login(client, password="nope")
    assert (await login(client)).status_code == 200
    for _ in range(4):
        assert (await login(client, password="nope")).status_code == 401
    assert (await login(client)).status_code == 200


async def test_rate_limit_is_per_client_ip_from_trusted_proxy(app, client):
    # ASGITransport's peer is 127.0.0.1: trust it as the proxy.
    app.dependency_overrides[get_client_ip_resolver] = lambda: ClientIPResolver(("127.0.0.1",))

    for _ in range(5):
        await login(client, password="nope", headers={"X-Real-IP": "10.0.0.1"})
    assert (await login(client, headers={"X-Real-IP": "10.0.0.1"})).status_code == 429
    assert (await login(client, headers={"X-Real-IP": "10.0.0.2"})).status_code == 200


async def test_x_real_ip_ignored_from_untrusted_peer(client):
    # Default override trusts nobody: a spoofed X-Real-IP must not dodge the limit.
    for i in range(5):
        await login(client, password="nope", headers={"X-Real-IP": f"10.0.0.{i}"})
    assert (await login(client, headers={"X-Real-IP": "10.9.9.9"})).status_code == 429


def test_rate_limiter_bounds_tracked_keys():
    limiter = LoginRateLimiter(max_tracked_keys=3)
    for i in range(10):
        limiter.record_failure(f"ip{i}")
    assert len(limiter._failures) == 3


# =============================================================================
# Tokens
# =============================================================================


def forge(claims: dict, secret: str = SECRET, algorithm: str = JWT_ALGORITHM) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": USERNAME,
        "role": "admin",
        "aud": TOKEN_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        **claims,
    }
    key = None if algorithm == "none" else secret
    return jwt.encode(payload, key, algorithm=algorithm)


async def test_missing_token(client):
    response = await client.get(ME)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_expired_token(client, config):
    token, _ = issue_admin_token(config, now=datetime.now(timezone.utc) - timedelta(hours=9))
    response = await client.get(ME, headers=bearer(token))
    assert response.status_code == 401
    assert response.json()["detail"]["message"] == "token expired"


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        forge({}, secret="t" * 64),  # wrong secret
        forge({"role": "operator"}),  # wrong role
        forge({"aud": "something-else"}),  # wrong audience
        forge({"sub": "someone-else"}),  # not the configured admin
        jwt.encode({"sub": USERNAME, "role": "admin"}, SECRET, algorithm=JWT_ALGORITHM),  # no exp/iat/aud
        forge({}, algorithm="none"),  # unsigned
    ],
    ids=["garbage", "wrong-secret", "wrong-role", "wrong-aud", "wrong-sub", "missing-claims", "alg-none"],
)
async def test_invalid_tokens(client, token):
    response = await client.get(ME, headers=bearer(token))
    assert response.status_code == 401
    assert response.json()["detail"]["message"] == "invalid token"


async def test_non_bearer_scheme(client, config):
    token, _ = issue_admin_token(config)
    response = await client.get(ME, headers={"Authorization": f"Basic {token}"})
    assert response.status_code == 401


# =============================================================================
# Not configured -> 503, backend still fine
# =============================================================================


@pytest.mark.parametrize(
    "unconfigured",
    [
        make_config(password_hash=""),
        make_config(username=""),
        make_config(password_hash="$2b$12"),  # what compose leaves of an unquoted hash
        make_config(password_hash="x" * 60),
        make_config(secret=""),
        make_config(secret="CHANGE_ME_IN_PRODUCTION"),
        make_config(secret="CHANGE_ME_IN_PRODUCTION_USE_STRONG_RANDOM_KEY"),
    ],
    ids=["no-hash", "no-username", "mangled-hash", "not-bcrypt", "empty-secret", "default-secret", "example-secret"],
)
async def test_unconfigured_admin_returns_503(app, client, unconfigured):
    assert not unconfigured.configured
    app.dependency_overrides[get_admin_auth_config] = lambda: unconfigured

    assert (await login(client)).status_code == 503
    token, _ = issue_admin_token(make_config())
    me = await client.get(ME, headers=bearer(token))
    assert me.status_code == 503
    assert me.json()["detail"]["message"] == "admin not configured"
    # The rest of the API is unaffected.
    assert (await client.get("/api/v1/health/live")).status_code == 200


def test_unset_environment_builds_unconfigured_without_raising(monkeypatch):
    for name in ("RUTH_ADMIN_USERNAME", "RUTH_ADMIN_PASSWORD_HASH", "RUTH_ADMIN_TRUSTED_PROXY_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    config = build_admin_auth_config(AdminAuthSettings(), SECRET)
    assert config.problem == "RUTH_ADMIN_USERNAME is not set"


# =============================================================================
# Existing routes: unchanged, no auth
# =============================================================================


@pytest.fixture
def app_with_mock_db(app):
    async def mock_db():
        yield MockAsyncSession()

    app.dependency_overrides[get_db] = mock_db
    return app


@pytest.mark.parametrize(
    "path",
    ["/api/v1/health/live", "/api/v1/settings/shift-schedule", "/api/v1/shifts/current"],
)
@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-real-token"}],
    ids=["no-token", "junk-token"],
)
@pytest.mark.usefixtures("app_with_mock_db")
async def test_existing_routes_need_no_token(client, path, headers):
    response = await client.get(path, headers=headers)
    assert response.status_code == 200, response.text


def test_only_admin_routes_require_admin():
    """require_admin pulls in the HTTPBearer scheme, which OpenAPI records as
    per-operation `security`. No other route in the app declares a security
    scheme, so `security` present <=> guarded by require_admin. (The public
    OpenAPI view is used because FastAPI >=0.140 no longer flattens included
    routers into app.routes.)"""
    schema = create_application().openapi()
    guarded, unguarded_admin = [], []
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if operation.get("security"):
                guarded.append((method, path))
            elif path.startswith("/api/v1/admin"):
                unguarded_admin.append((method, path))

    assert ("get", ME) in guarded
    assert all(p.startswith("/api/v1/admin/") for _, p in guarded), guarded
    # Login is the only admin route without the guard.
    assert unguarded_admin == [("post", LOGIN)]
