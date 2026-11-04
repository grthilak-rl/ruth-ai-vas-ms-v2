"""Who the report is for: customer name and logo.

Stored as the `report_branding` app setting and edited by an admin under
Settings -> Report branding. The logo is a file in ``report_branding_dir``;
the setting holds only its name, so a restored database never points
outside that directory. No row means no branding: the cover then shows the
title alone.
"""

import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.app_setting import REPORT_BRANDING_KEY, AppSetting

logger = get_logger(__name__)

ASSETS = Path(__file__).resolve().parents[2] / "assets"
VENDOR_LOGO = ASSETS / "report" / "vendor_logo.jpeg"

MAX_LOGO_BYTES = 1024 * 1024
#: Uploaded logos are scaled down to fit this box; the cover draws at most
#: 170 × 64 pt, so this is ample for print.
LOGO_MAX_PX = (600, 300)
ACCEPTED_FORMATS = {"PNG", "JPEG"}


class LogoError(ValueError):
    """An upload that is not a usable logo; the message is for the admin."""


class ReportBranding(BaseModel):
    customer_name: str | None = Field(default=None, max_length=120)
    #: File name inside report_branding_dir.
    logo_file_name: str | None = None

    def logo_file(self) -> Path | None:
        """The logo, when it is a readable file inside the branding dir."""
        if not self.logo_file_name:
            return None
        root = Path(get_settings().report_branding_dir).resolve()
        path = (root / self.logo_file_name).resolve()
        if path.is_relative_to(root) and path.is_file():
            return path
        logger.warning("Report logo not found, cover shows the name only", path=str(path))
        return None


async def _row(db: AsyncSession) -> AppSetting | None:
    return (
        await db.execute(select(AppSetting).where(AppSetting.key == REPORT_BRANDING_KEY))
    ).scalars().first()


async def get_branding(db: AsyncSession) -> ReportBranding:
    row = await _row(db)
    if row is None:
        return ReportBranding()
    try:
        return ReportBranding.model_validate(row.value)
    except Exception as exc:  # noqa: BLE001
        logger.error("Stored report branding is unreadable, using none", error=str(exc))
        return ReportBranding()


async def save_branding(db: AsyncSession, branding: ReportBranding, by: str | None) -> ReportBranding:
    row = await _row(db)
    value = branding.model_dump()
    if row is None:
        db.add(AppSetting(key=REPORT_BRANDING_KEY, value=value, updated_by=by))
    else:
        row.value = value
        row.updated_by = by
    await db.commit()
    return branding


def prepare_logo(data: bytes) -> bytes:
    """Validate an upload and re-encode it as a bounded PNG.

    Re-encoding means what is stored is always a plain image Pillow wrote,
    whatever the upload carried; transparency survives.
    """
    from PIL import Image, UnidentifiedImageError

    if len(data) > MAX_LOGO_BYTES:
        raise LogoError("The logo must be 1 MB or smaller.")
    try:
        with Image.open(BytesIO(data)) as probe:
            fmt = probe.format
            probe.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise LogoError("The file is not a readable image.") from exc
    if fmt not in ACCEPTED_FORMATS:
        raise LogoError("The logo must be a PNG or JPEG image.")

    with Image.open(BytesIO(data)) as image:
        image = image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
        image.thumbnail(LOGO_MAX_PX, Image.LANCZOS)
        out = BytesIO()
        image.save(out, "PNG", optimize=True)
    return out.getvalue()


def store_logo(png: bytes) -> str:
    """Write a prepared logo; returns its file name. Old logos are removed."""
    root = Path(get_settings().report_branding_dir)
    root.mkdir(parents=True, exist_ok=True)
    name = f"logo-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.png"
    tmp = root / f".{name}.tmp"
    tmp.write_bytes(png)
    tmp.replace(root / name)
    remove_logos(keep=name)
    return name


def remove_logos(keep: str | None = None) -> None:
    root = Path(get_settings().report_branding_dir)
    if not root.is_dir():
        return
    for path in root.glob("logo-*.png"):
        if path.name != keep:
            path.unlink(missing_ok=True)
