"""Model store: id rules, auth on every route, cleanup lifespan wiring.

No database needed. DB-backed behaviour (uploads, quota, tombstones) is in
tests/model_store/.
"""

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1 import admin
from app.core.admin_auth import ClientIPResolver, get_admin_auth_config
from app.main import create_application
from app.services.model_store.ids import (
    RESERVED_MODEL_IDS,
    model_id_base_from_name,
    model_id_candidates,
    model_id_problem,
)
from tests.unit.test_admin_auth import make_config

U = str(uuid.uuid4())
BASE = "/api/v1/admin/model-store"

#: Every model-store route, with placeholder ids.
MODEL_STORE_ROUTES = [
    ("GET", f"{BASE}/models"),
    ("POST", f"{BASE}/models"),
    ("GET", f"{BASE}/models/{U}"),
    ("PATCH", f"{BASE}/models/{U}"),
    ("DELETE", f"{BASE}/models/{U}"),
    ("GET", f"{BASE}/models/{U}/files"),
    ("DELETE", f"{BASE}/models/{U}/files/{U}"),
    ("GET", f"{BASE}/models/{U}/uploads"),
    ("POST", f"{BASE}/models/{U}/uploads"),
    ("GET", f"{BASE}/uploads/{U}"),
    ("PUT", f"{BASE}/uploads/{U}/chunks/0"),
    ("POST", f"{BASE}/uploads/{U}/complete"),
    ("DELETE", f"{BASE}/uploads/{U}"),
]


# =============================================================================
# model_id rules
# =============================================================================


@pytest.mark.parametrize("model_id", sorted(RESERVED_MODEL_IDS))
def test_reserved_ids_rejected(model_id):
    assert "reserved" in model_id_problem(model_id)


def test_reserved_set_is_exactly_the_platform_ids():
    expected = {
        "fall_detection",
        "ppe_detection",
        "geo_fencing",
        "tank_overflow_monitoring",
        "chane_tank_monitor",
        "helmet_detection",
        "fire_detection",
        "intrusion_detection",
        "chane_tank_overflow",
    }
    assert expected == RESERVED_MODEL_IDS


@pytest.mark.parametrize(
    "model_id",
    ["ab", "1model", "Model", "model-x", "a" * 49, "test_model", "dummy_x", "broken_y", ""],
)
def test_invalid_ids_rejected(model_id):
    assert model_id_problem(model_id) is not None


@pytest.mark.parametrize("model_id", ["ppe_six_items", "abc", "harness_v2", "a" * 48])
def test_valid_ids_accepted(model_id):
    assert model_id_problem(model_id) is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("PPE — six items", "ppe_six_items"),
        ("  Harness Detector v2 ", "harness_detector_v2"),
        ("3D Fall", "model_3d_fall"),
        ("Test model", "model_test_model"),
        ("x", "x_model"),
        ("!!!", "model"),
    ],
)
def test_model_id_from_display_name(name, expected):
    base = model_id_base_from_name(name)
    assert base == expected
    assert model_id_problem(base) is None


def test_generation_skips_reserved_base():
    candidates = model_id_candidates("Fall Detection")
    assert next(candidates) == "fall_detection"  # reserved: the service skips it
    assert next(candidates) == "fall_detection_2"
    assert model_id_problem("fall_detection_2") is None


# =============================================================================
# Auth: every model-store route rejects requests without a valid admin token
# =============================================================================


@pytest.fixture
async def client():
    app = create_application()
    app.dependency_overrides[get_admin_auth_config] = make_config
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.parametrize(("method", "path"), MODEL_STORE_ROUTES)
@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer junk"}], ids=["no-token", "junk-token"]
)
async def test_every_model_store_route_requires_admin(client, method, path, headers):
    response = await client.request(method, path, headers=headers, content=b"x")
    assert response.status_code == 401, (method, path, response.text)


def _shape(path: str) -> str:
    """Path with every parameter segment replaced by {}."""
    return "/".join(
        "{}" if seg.startswith("{") or seg == U or seg.isdigit() else seg
        for seg in path.split("/")
    )


def test_route_list_covers_every_model_store_operation():
    """Guards the auth test above: a new route must be added to MODEL_STORE_ROUTES."""
    schema = create_application().openapi()
    actual = {
        (method.upper(), _shape(path))
        for path, operations in schema["paths"].items()
        if path.startswith(BASE)
        for method in operations
    }
    assert actual == {(method, _shape(path)) for method, path in MODEL_STORE_ROUTES}


# =============================================================================
# Cleanup task is wired through the router lifespan
# =============================================================================


async def test_cleanup_task_runs_inside_router_lifespan():
    app = create_application()
    # Only the admin router's own (merged) lifespan: no DB or app startup.
    async with admin.router.lifespan_context(app):
        names = {t.get_name() for t in asyncio.all_tasks()}
        assert "model-store-staging-cleanup" in names
    await asyncio.sleep(0)
    names = {t.get_name() for t in asyncio.all_tasks() if not t.done()}
    assert "model-store-staging-cleanup" not in names


# =============================================================================
# Carry-over: trusted proxy re-resolves when the frontend IP changes
# =============================================================================


async def test_proxy_resolver_picks_up_new_frontend_ip(monkeypatch):
    answers = {"frontend": ["172.21.0.6"]}

    async def fake_getaddrinfo(host, _port):
        return [(None, None, None, None, (ip, 0)) for ip in answers[host]]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    clock = {"now": 1000.0}
    monkeypatch.setattr("app.core.admin_auth.time.monotonic", lambda: clock["now"])

    resolver = ClientIPResolver(("frontend",), cache_seconds=60, miss_refresh_seconds=5)

    class Req:
        def __init__(self, peer):
            self.client = type("C", (), {"host": peer})()
            self.headers = {"x-real-ip": "10.1.2.3"}

    assert await resolver.resolve(Req("172.21.0.6")) == "10.1.2.3"

    # Frontend container recreated with a new IP.
    answers["frontend"] = ["172.21.0.9"]
    clock["now"] += 2  # cache fresh: a miss within 5s does not re-resolve
    assert await resolver.resolve(Req("172.21.0.9")) == "172.21.0.9"
    clock["now"] += 4  # cache now 6s old: a miss re-resolves immediately
    assert await resolver.resolve(Req("172.21.0.9")) == "10.1.2.3"
    # An untrusted peer still cannot spoof X-Real-IP.
    assert await resolver.resolve(Req("192.168.1.50")) == "192.168.1.50"
