"""Product (white-label) branding: whose product this is.

Separate from the customer branding in ``app.services.report.branding``
(the client named on report covers). A site holds a few brand profiles —
Visics, RuthLabs for investor demos, a licensee's — and exactly one is
active. The active one names the product in the UI (header, sign-in page,
tab title, favicon), in report covers and footers, and in export file names.

Stored as the ``product_branding`` app setting. Images are files in
``product_branding_dir``; the setting holds only their names. Names that
start with ``builtin-`` are images shipped with the backend in
``app/assets/branding`` (the seeded Visics profile uses them), so a fresh
install shows the Visics brand with nothing uploaded.

No row, or an unreadable one, means the built-in Visics profile: nothing
here can leave the UI without a brand.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.app_setting import PRODUCT_BRANDING_KEY, AppSetting
from app.services.report.branding import LogoError, encode_png, open_upload

logger = get_logger(__name__)

BUILTIN_DIR = Path(__file__).resolve().parents[1] / "assets" / "branding"
BUILTIN_PREFIX = "builtin-"

Slot = Literal["logo_light", "logo_dark", "icon"]
SLOTS: tuple[str, ...] = ("logo_light", "logo_dark", "icon")

MAX_PROFILES = 10
#: Logos fit this box (the header draws 48 px high, the report cover 60 × 34 pt).
LOGO_MAX_PX = (600, 300)
#: The icon is stored as one square PNG; browsers scale it for the favicon
#: and the home-screen icon.
ICON_PX = 256
#: Wider than this (or taller) is not an icon.
ICON_MAX_ASPECT = 1.25

DEFAULT_PROFILE_ID = "visics"
DEFAULT_REPORT_NOTE = "AI video analytics · Confidential: for the customer's internal use"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}\.png$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class BrandingError(ValueError):
    """A request that cannot be applied; the message is for the admin."""


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def _relative_luminance(hex_colour: str) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_on_white(hex_colour: str) -> float:
    return 1.05 / (_relative_luminance(hex_colour) + 0.05)


#: Graphics and large text need 3:1 against the white page (WCAG 1.4.11).
MIN_ACCENT_CONTRAST = 3.0


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


class BrandFields(BaseModel):
    """What an admin edits on a profile (images are uploaded separately)."""

    #: The profile's label in Settings ("RuthLabs (investor demo)"); never shown to users.
    name: str = Field(min_length=1, max_length=60)
    #: The product as users see it: tab title, header alt text, report footer.
    product_name: str = Field(min_length=1, max_length=60)
    #: Optional shorter form for tight places; falls back to product_name.
    short_name: str | None = Field(default=None, max_length=30)
    #: What the chat assistant is called ("Ask Visi"); falls back to the short name.
    assistant_name: str | None = Field(default=None, max_length=30)
    #: Optional accent colour (#rrggbb), at least 3:1 on white.
    accent: str | None = None
    #: The line beside "Prepared by" on the report cover. Empty draws nothing.
    report_note: str | None = Field(default=None, max_length=120)

    @field_validator("name", "product_name", mode="before")
    @classmethod
    def _required_text(cls, v):
        v = _clean(v) if isinstance(v, str) else v
        if not v:
            raise ValueError("must not be empty")
        return v

    @field_validator("short_name", "assistant_name", "report_note", mode="before")
    @classmethod
    def _optional_text(cls, v):
        return _clean(v) if isinstance(v, str) else v

    @field_validator("accent", mode="before")
    @classmethod
    def _accent(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        v = v.strip()
        if not _HEX_RE.match(v):
            raise ValueError("accent must be a colour like #2a78d6")
        if contrast_on_white(v) < MIN_ACCENT_CONTRAST:
            raise ValueError(
                f"accent {v} is too light to read on white "
                f"({contrast_on_white(v):.1f}:1, needs {MIN_ACCENT_CONTRAST:.0f}:1)"
            )
        return v.lower()


class BrandProfile(BrandFields):
    id: str
    #: slot -> file name (see module docstring); absent or None means not set.
    images: dict[str, str | None] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError("invalid profile id")
        return v

    @field_validator("images")
    @classmethod
    def _images(cls, v: dict[str, str | None]) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for slot, name in v.items():
            if slot not in SLOTS:
                continue
            out[slot] = name if name and _FILE_RE.match(name) else None
        return out

    @property
    def display_short_name(self) -> str:
        return self.short_name or self.product_name

    @property
    def display_assistant_name(self) -> str:
        return self.assistant_name or self.display_short_name


class ProductBranding(BaseModel):
    active_id: str
    profiles: list[BrandProfile]

    def profile(self, profile_id: str) -> BrandProfile | None:
        return next((p for p in self.profiles if p.id == profile_id), None)

    @property
    def active(self) -> BrandProfile:
        # Validation on save keeps active_id pointing at a profile; this guards
        # a hand-edited row.
        return self.profile(self.active_id) or self.profiles[0]


def default_profile() -> BrandProfile:
    return BrandProfile(
        id=DEFAULT_PROFILE_ID,
        name="Visics",
        product_name="Visics AI",
        assistant_name="Visi",
        report_note=DEFAULT_REPORT_NOTE,
        images={
            "logo_light": "builtin-visics-logo-light.png",
            "logo_dark": None,
            "icon": "builtin-visics-icon.png",
        },
    )


def default_branding() -> ProductBranding:
    return ProductBranding(active_id=DEFAULT_PROFILE_ID, profiles=[default_profile()])


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

#: The active brand is read on every page load (public endpoint) and every
#: report; it changes rarely. Cached in-process, dropped on every save, and
#: re-read at least this often in case another process wrote it.
_CACHE_SECONDS = 10.0
_cache: tuple[float, ProductBranding] | None = None


def clear_cache() -> None:
    global _cache
    _cache = None


async def _row(db: AsyncSession) -> AppSetting | None:
    return (
        await db.execute(select(AppSetting).where(AppSetting.key == PRODUCT_BRANDING_KEY))
    ).scalars().first()


async def get_branding(db: AsyncSession, *, fresh: bool = False) -> ProductBranding:
    global _cache
    now = time.monotonic()
    if not fresh and _cache is not None and now - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    row = await _row(db)
    branding = default_branding()
    if row is not None:
        try:
            branding = ProductBranding.model_validate(row.value)
            if not branding.profiles:
                raise ValueError("no profiles")
        except Exception as exc:  # noqa: BLE001
            logger.error("Stored product branding is unreadable, using Visics", error=str(exc))
            branding = default_branding()
    _cache = (now, branding)
    return branding


async def load_for_edit(db: AsyncSession) -> ProductBranding:
    """A fresh, private copy to change and save (never the cached object)."""
    return (await get_branding(db, fresh=True)).model_copy(deep=True)


async def get_active(db: AsyncSession) -> BrandProfile:
    return (await get_branding(db)).active


async def save_branding(db: AsyncSession, branding: ProductBranding, by: str | None) -> ProductBranding:
    if branding.profile(branding.active_id) is None:
        raise BrandingError("The active profile does not exist.")
    row = await _row(db)
    value = branding.model_dump(mode="json")
    if row is None:
        db.add(AppSetting(key=PRODUCT_BRANDING_KEY, value=value, updated_by=by))
    else:
        row.value = value
        row.updated_by = by
    await db.commit()
    clear_cache()
    return branding


async def updated_meta(db: AsyncSession) -> tuple[str | None, object | None]:
    row = await _row(db)
    return (row.updated_by, row.updated_at) if row else (None, None)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def add_profile(branding: ProductBranding, fields: BrandFields) -> BrandProfile:
    if len(branding.profiles) >= MAX_PROFILES:
        raise BrandingError(f"At most {MAX_PROFILES} brand profiles.")
    profile = BrandProfile(id=f"p-{uuid.uuid4().hex[:8]}", **fields.model_dump())
    branding.profiles.append(profile)
    return profile


def update_profile(branding: ProductBranding, profile_id: str, fields: BrandFields) -> BrandProfile:
    profile = require_profile(branding, profile_id)
    for key, value in fields.model_dump().items():
        setattr(profile, key, value)
    return profile


def remove_profile(branding: ProductBranding, profile_id: str) -> BrandProfile:
    profile = require_profile(branding, profile_id)
    if profile_id == branding.active_id:
        raise BrandingError("The active profile cannot be deleted. Activate another one first.")
    branding.profiles = [p for p in branding.profiles if p.id != profile_id]
    return profile


def activate(branding: ProductBranding, profile_id: str) -> BrandProfile:
    profile = require_profile(branding, profile_id)
    branding.active_id = profile_id
    return profile


def require_profile(branding: ProductBranding, profile_id: str) -> BrandProfile:
    profile = branding.profile(profile_id)
    if profile is None:
        raise LookupError(profile_id)
    return profile


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def image_path(profile: BrandProfile, slot: str) -> Path | None:
    """The image file for a slot, when it is a readable file in its directory."""
    name = profile.images.get(slot)
    if not name or not _FILE_RE.match(name):
        return None
    root = (BUILTIN_DIR if name.startswith(BUILTIN_PREFIX) else Path(get_settings().product_branding_dir)).resolve()
    path = (root / name).resolve()
    if path.is_relative_to(root) and path.is_file():
        return path
    logger.warning("Product brand image missing", profile=profile.id, slot=slot, path=str(path))
    return None


def image_version(profile: BrandProfile, slot: str) -> str | None:
    """Changes whenever the image does (file names are unique per upload)."""
    name = profile.images.get(slot)
    if not name or image_path(profile, slot) is None:
        return None
    return hashlib.sha256(f"{profile.id}/{name}".encode()).hexdigest()[:12]


def prepare_image(slot: str, data: bytes) -> bytes:
    """Validate and re-encode an upload for a slot. Raises LogoError."""
    if slot not in SLOTS:
        raise LogoError("Unknown image slot.")
    what = "icon" if slot == "icon" else "logo"
    with open_upload(data, what) as image:
        if slot != "icon":
            return encode_png(image, LOGO_MAX_PX)
        w, h = image.size
        if max(w, h) / max(1, min(w, h)) > ICON_MAX_ASPECT:
            raise LogoError("The icon must be square (or nearly): it is shown as the browser tab icon.")
        from PIL import Image

        image = image.convert("RGBA")
        side = max(w, h)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(image, ((side - w) // 2, (side - h) // 2))
        return encode_png(square.resize((ICON_PX, ICON_PX), Image.LANCZOS), (ICON_PX, ICON_PX))


def store_image(profile_id: str, slot: str, png: bytes) -> str:
    """Write a prepared image; returns its file name."""
    if not _ID_RE.match(profile_id) or slot not in SLOTS:
        raise LogoError("Invalid profile or slot.")
    root = Path(get_settings().product_branding_dir)
    root.mkdir(parents=True, exist_ok=True)
    name = f"{profile_id}-{slot.replace('_', '-')}-{uuid.uuid4().hex[:12]}.png"
    tmp = root / f".{name}.tmp"
    tmp.write_bytes(png)
    tmp.replace(root / name)
    return name


def delete_image_file(name: str | None) -> None:
    """Remove an uploaded image. Built-in images are never touched."""
    if not name or name.startswith(BUILTIN_PREFIX) or not _FILE_RE.match(name):
        return
    root = Path(get_settings().product_branding_dir).resolve()
    path = (root / name).resolve()
    if path.is_relative_to(root):
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# What others read
# ---------------------------------------------------------------------------

PUBLIC_ASSET_PATH = "/api/v1/branding/asset"


def public_view(profile: BrandProfile) -> dict:
    """The active brand as the sign-in page may see it: nothing else.

    No profile ids, no other profiles, no audit fields.
    """

    def url(slot: str) -> str | None:
        v = image_version(profile, slot)
        return f"{PUBLIC_ASSET_PATH}/{slot}?v={v}" if v else None

    return {
        "product_name": profile.product_name,
        "short_name": profile.display_short_name,
        "assistant_name": profile.display_assistant_name,
        "accent": profile.accent,
        "logo_light": url("logo_light"),
        "logo_dark": url("logo_dark"),
        "icon": url("icon"),
    }


@dataclass(frozen=True)
class ReportProductBrand:
    """The product brand as a report is built with it (a snapshot)."""

    product_name: str = "Visics AI"
    report_note: str | None = DEFAULT_REPORT_NOTE
    logo: Path | None = None
    accent: str | None = None

    @classmethod
    def of(cls, profile: BrandProfile) -> ReportProductBrand:
        return cls(
            product_name=profile.product_name,
            report_note=profile.report_note,
            logo=image_path(profile, "logo_light"),
            accent=profile.accent,
        )

    @classmethod
    def builtin(cls) -> ReportProductBrand:
        return cls.of(default_profile())


async def report_brand(db: AsyncSession) -> ReportProductBrand:
    return ReportProductBrand.of(await get_active(db))


def file_slug(product_name: str) -> str:
    """A product name as a file-name prefix: "Ruth AI" -> "ruth-ai"."""
    slug = re.sub(r"[^a-z0-9]+", "-", product_name.lower()).strip("-")
    return slug[:40].strip("-") or "analytics"
