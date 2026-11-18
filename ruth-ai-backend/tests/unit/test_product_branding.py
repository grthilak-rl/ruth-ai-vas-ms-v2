"""Product (white-label) branding: profiles, uploads, the open endpoint,
admin-only writes, and what reports carry.

No database: the app_settings row lives in a tiny in-memory session.
"""

import re
from io import BytesIO
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.core.admin_auth import (
    AdminAuthSettings,
    build_admin_auth_config,
    get_admin_auth_config,
    issue_admin_token,
)
from app.core.config import get_settings
from app.deps.db import get_db
from app.main import create_application
from app.services import product_branding as pb
from app.services.report.branding import LogoError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeDB:
    """Just enough AsyncSession for one app_settings row."""

    def __init__(self) -> None:
        self.row = None
        self.commits = 0

    async def execute(self, _stmt):
        row = self.row
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: row))

    def add(self, obj) -> None:
        self.row = obj

    async def commit(self) -> None:
        self.commits += 1


def png(size=(400, 200), colour=(20, 40, 200, 255), mode="RGBA") -> bytes:
    out = BytesIO()
    Image.new(mode, size, colour if mode == "RGBA" else colour[:3]).save(out, "PNG")
    return out.getvalue()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    pb.clear_cache()
    monkeypatch.setattr(get_settings(), "product_branding_dir", str(tmp_path / "brand"))
    yield
    pb.clear_cache()


@pytest.fixture
def db() -> FakeDB:
    return FakeDB()


@pytest.fixture
def admin_config():
    import bcrypt

    return build_admin_auth_config(
        AdminAuthSettings(
            ruth_admin_username="admin",
            ruth_admin_password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt(rounds=4)).decode(),
        ),
        "s" * 64,
    )


@pytest.fixture
async def client(db, admin_config):
    app = create_application()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_admin_auth_config] = lambda: admin_config
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def auth(admin_config) -> dict[str, str]:
    token, _ = issue_admin_token(admin_config)
    return {"Authorization": f"Bearer {token}"}


ADMIN = "/api/v1/admin/product-branding"
RUTHLABS = {"name": "RuthLabs", "product_name": "Ruth AI", "assistant_name": "Ruth"}

# ---------------------------------------------------------------------------
# Model and defaults
# ---------------------------------------------------------------------------


async def test_no_row_means_the_builtin_visics_profile(db):
    branding = await pb.get_branding(db)
    assert branding.active_id == "visics"
    active = branding.active
    assert (active.product_name, active.display_assistant_name) == ("Visics AI", "Visi")
    # The seeded images ship with the backend; nothing has to be uploaded.
    assert pb.image_path(active, "logo_light").is_file()
    assert pb.image_path(active, "icon").is_file()
    assert pb.image_path(active, "logo_dark") is None


async def test_unreadable_row_falls_back_to_visics(db):
    db.row = SimpleNamespace(value={"active_id": "x", "profiles": "garbage"})
    assert (await pb.get_branding(db)).active.product_name == "Visics AI"


def test_migration_seed_matches_the_builtin_default():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "migrations/versions/2026_11_18_product_branding.py"
    spec = importlib.util.spec_from_file_location("seed", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert pb.ProductBranding.model_validate(module.SEED) == pb.default_branding()


@pytest.mark.parametrize(
    "accent, ok",
    [("#2A78D6", True), ("#184f95", True), ("#ffff00", False), ("#eeeeee", False), ("blue", False), ("#12345", False)],
)
def test_accent_must_be_hex_and_readable_on_white(accent, ok):
    if ok:
        assert pb.BrandFields(name="a", product_name="b", accent=accent).accent == accent.lower()
    else:
        with pytest.raises(ValueError):
            pb.BrandFields(name="a", product_name="b", accent=accent)


def test_text_fields_are_trimmed_and_required():
    f = pb.BrandFields(name="  Ruth   Labs ", product_name="Ruth AI", short_name="  ", accent="")
    assert (f.name, f.short_name, f.accent) == ("Ruth Labs", None, None)
    with pytest.raises(ValueError):
        pb.BrandFields(name="x", product_name="   ")


def test_profile_rules():
    branding = pb.default_branding()
    added = pb.add_profile(branding, pb.BrandFields(**RUTHLABS))
    assert re.fullmatch(r"p-[0-9a-f]{8}", added.id)
    with pytest.raises(pb.BrandingError):
        pb.remove_profile(branding, "visics")  # active
    pb.activate(branding, added.id)
    assert branding.active.product_name == "Ruth AI"
    pb.remove_profile(branding, "visics")
    assert [p.id for p in branding.profiles] == [added.id]
    with pytest.raises(LookupError):
        pb.activate(branding, "nope")
    for i in range(pb.MAX_PROFILES - 1):
        pb.add_profile(branding, pb.BrandFields(name=f"n{i}", product_name="p"))
    with pytest.raises(pb.BrandingError):
        pb.add_profile(branding, pb.BrandFields(name="one too many", product_name="p"))


def test_file_slug():
    assert pb.file_slug("Visics AI") == "visics-ai"
    assert pb.file_slug("Ruth AI") == "ruth-ai"
    assert pb.file_slug("  ACME / Vision™ ") == "acme-vision"
    assert pb.file_slug("™™") == "analytics"


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def test_logo_is_reencoded_and_bounded():
    out = pb.prepare_image("logo_light", png((1800, 400)))
    with Image.open(BytesIO(out)) as im:
        assert im.format == "PNG" and im.width <= 600 and im.height <= 300


def test_icon_is_padded_to_a_256_square():
    out = pb.prepare_image("icon", png((300, 260)))
    with Image.open(BytesIO(out)) as im:
        assert im.size == (256, 256)


def test_icon_must_be_nearly_square():
    with pytest.raises(LogoError, match="square"):
        pb.prepare_image("icon", png((600, 200)))


@pytest.mark.parametrize(
    "data",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"GIF89a" + b"\0" * 100,
        b"not an image",
        b"\x89PNG\r\n\x1a\n" + b"\0" * 2048 + b"<script>",  # truncated polyglot
    ],
)
def test_uploads_other_than_png_or_jpeg_are_refused(data):
    with pytest.raises(LogoError):
        pb.prepare_image("logo_light", data)


def test_oversized_upload_is_refused():
    with pytest.raises(LogoError, match="1 MB"):
        pb.prepare_image("logo_light", b"\x89PNG" + b"\0" * (1024 * 1024 + 1))


def test_decompression_bomb_is_refused(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(LogoError):
        pb.prepare_image("logo_light", png((200, 200)))


def test_image_names_cannot_leave_their_directory(tmp_path):
    (tmp_path / "secret.png").write_bytes(png())
    for name in ("../secret.png", "/etc/passwd", "..%2fsecret.png", "builtin-../../x.png", "x.svg"):
        profile = pb.BrandProfile(id="p-1", name="n", product_name="p", images={"icon": name})
        assert pb.image_path(profile, "icon") is None


def test_builtin_images_are_never_deleted():
    pb.delete_image_file("builtin-visics-icon.png")
    assert (pb.BUILTIN_DIR / "builtin-visics-icon.png").is_file()


def test_public_view_exposes_the_active_brand_only():
    view = pb.public_view(pb.default_profile())
    assert set(view) == {"product_name", "short_name", "assistant_name", "accent", "logo_light", "logo_dark", "icon"}
    assert view["icon"].startswith("/api/v1/branding/asset/icon?v=")
    assert view["logo_dark"] is None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


async def test_open_endpoint_needs_no_sign_in(client):
    r = await client.get("/api/v1/branding")
    assert r.status_code == 200
    assert r.json()["product_name"] == "Visics AI"
    assert r.headers["cache-control"] == "no-cache"
    icon = await client.get(r.json()["icon"])
    assert icon.status_code == 200
    assert icon.headers["content-type"] == "image/png"
    assert icon.headers["x-content-type-options"] == "nosniff"
    assert "immutable" in icon.headers["cache-control"]
    # The bare URL (the favicon in index.html) follows switches: not cached.
    assert (await client.get("/api/v1/branding/asset/icon")).headers["cache-control"] == "no-cache"
    assert (await client.get("/api/v1/branding/asset/logo_dark")).status_code == 404
    # Request validation errors are 400 in this app (app/core/errors.py).
    assert (await client.get("/api/v1/branding/asset/secret")).status_code == 400


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", ""),
        ("POST", "/profiles"),
        ("PUT", "/profiles/visics"),
        ("DELETE", "/profiles/visics"),
        ("POST", "/profiles/visics/activate"),
        ("PUT", "/profiles/visics/images/icon"),
        ("GET", "/profiles/visics/images/icon"),
        ("DELETE", "/profiles/visics/images/icon"),
    ],
)
async def test_every_admin_route_needs_an_admin_token(client, method, path):
    r = await client.request(method, ADMIN + path, json=RUTHLABS)
    assert r.status_code == 401


async def test_create_upload_switch_and_back(client, auth, db):
    r = await client.post(f"{ADMIN}/profiles", json=RUTHLABS, headers=auth)
    assert r.status_code == 201
    ruth = next(p for p in r.json()["profiles"] if p["name"] == "RuthLabs")
    assert not ruth["active"] and ruth["images"]["logo_light"] is None

    r = await client.put(f"{ADMIN}/profiles/{ruth['id']}/images/logo_light", content=png(), headers=auth)
    assert r.status_code == 200
    v1 = next(p for p in r.json()["profiles"] if p["id"] == ruth["id"])["images"]["logo_light"]
    assert v1

    # Replacing an image gives it a new version and removes the old file.
    r = await client.put(f"{ADMIN}/profiles/{ruth['id']}/images/logo_light", content=png(colour=(9, 9, 9, 255)), headers=auth)
    v2 = next(p for p in r.json()["profiles"] if p["id"] == ruth["id"])["images"]["logo_light"]
    assert v2 and v2 != v1
    assert len(list((pb.Path(get_settings().product_branding_dir)).glob("*.png"))) == 1

    r = await client.post(f"{ADMIN}/profiles/{ruth['id']}/activate", headers=auth)
    assert r.json()["active_id"] == ruth["id"]
    public = (await client.get("/api/v1/branding")).json()
    assert public["product_name"] == "Ruth AI"
    assert public["assistant_name"] == "Ruth"
    assert public["icon"] is None  # RuthLabs has no icon yet; the UI keeps its own
    assert (await client.get(public["logo_light"])).status_code == 200

    # The active profile cannot be deleted.
    assert (await client.delete(f"{ADMIN}/profiles/{ruth['id']}", headers=auth)).status_code == 409

    await client.post(f"{ADMIN}/profiles/visics/activate", headers=auth)
    assert (await client.get("/api/v1/branding")).json()["product_name"] == "Visics AI"
    assert db.row.updated_by == "admin"


async def test_bad_requests(client, auth):
    assert (await client.post(f"{ADMIN}/profiles/nope/activate", headers=auth)).status_code == 404
    r = await client.put(f"{ADMIN}/profiles/visics/images/icon", content=b"<svg/>", headers=auth)
    assert r.status_code == 422 and r.json()["detail"]["error"] == "invalid_image"
    r = await client.put(f"{ADMIN}/profiles/visics/images/icon", content=b"\0" * (1024 * 1024 + 10), headers=auth)
    assert r.status_code == 413
    r = await client.post(f"{ADMIN}/profiles", json={**RUTHLABS, "accent": "#ffff66"}, headers=auth)
    assert r.status_code == 400 and "too light" in r.text


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def _drawn_strings(monkeypatch) -> list[str]:
    from reportlab.pdfgen.canvas import Canvas

    seen: list[str] = []
    for name in ("drawString", "drawRightString"):
        original = getattr(Canvas, name)

        def spy(self, x, y, text, *a, _orig=original, **k):
            seen.append(text)
            return _orig(self, x, y, text, *a, **k)

        monkeypatch.setattr(Canvas, name, spy)
    return seen


def test_report_carries_both_brands(monkeypatch):
    from tests.unit.test_customer_report import run

    from app.services.report.pdf import render_pdf

    seen = _drawn_strings(monkeypatch)
    r = run([])
    r.product = pb.ReportProductBrand(product_name="Ruth AI", report_note="Prepared for investors", logo=None)
    pdf = render_pdf(r)
    assert pdf.startswith(b"%PDF")
    assert "ACME" in seen  # the customer, on the cover
    assert "Ruth AI" in seen  # no product logo: the cover names the product
    assert "Prepared for investors" in seen
    assert any(s.startswith("Ruth AI  ·  Page ") for s in seen)  # footer
    assert b"Ruth AI" in pdf  # PDF author


def test_report_default_is_visics_with_logo(monkeypatch):
    from tests.unit.test_customer_report import run

    from app.services.report.pdf import render_pdf

    seen = _drawn_strings(monkeypatch)
    r = run([])
    assert r.product.product_name == "Visics AI" and r.product.logo is not None
    render_pdf(r)
    assert pb.DEFAULT_REPORT_NOTE in seen
    assert any(s.startswith("Visics AI  ·  Page ") for s in seen)


def test_report_survives_an_unreadable_product_logo(monkeypatch, tmp_path):
    from tests.unit.test_customer_report import run

    from app.services.report.pdf import render_pdf

    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png")
    seen = _drawn_strings(monkeypatch)
    r = run([])
    r.product = pb.ReportProductBrand(product_name="Ruth AI", logo=bad, accent="#184f95")
    assert render_pdf(r).startswith(b"%PDF")
    assert "Ruth AI" in seen
