"""Projects: reads, per-project counts, and the backup taken before Start.

Projects are tags (app/models/project_tag.py). Starting the next project
opens a new row and switches cameras (app/services/project_lifecycle.py);
nothing is moved. Until 2026-11 this module also archived the previous
project's rows out of the live tables; that flow is retired, and the one
project it archived was copied back and tagged by the projects_as_tags
migration. The pre-start pg_dump is kept: it is cheap (tens of MB) and is
the backup everyone reaches for first.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.project_scope import ALL_PROJECTS
from app.models import CustomerReport, Event, Evidence, Project, StreamSession, Violation, ViolationExport
from app.services.exceptions import ServiceError

logger = get_logger(__name__)

#: Per-project counts shown in Settings -> Project, by label.
COUNTED = {
    "violations": Violation,
    "events": Event,
    "evidence": Evidence,
    "stream_sessions": StreamSession,
    "customer_reports": CustomerReport,
    "violation_exports": ViolationExport,
}


# -----------------------------------------------------------------------------
# Errors
# -----------------------------------------------------------------------------


class ProjectError(ServiceError):
    """Base for project errors."""


class ConfirmationMismatchError(ProjectError):
    """The retyped project name did not match."""

    def __init__(self) -> None:
        super().__init__("The confirmation text does not match the project name exactly.")


class BackupUnavailableError(ProjectError):
    """pg_dump cannot run, so Start must not proceed."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"Cannot take the pre-start backup: {reason}. Refusing to start without one.",
            details={"reason": reason},
        )


class BackupFailedError(ProjectError):
    """pg_dump ran but did not produce a usable dump."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Pre-start backup failed: {reason}", details={"reason": reason})


class ProjectNameInUseError(ProjectError):
    """Two projects would claim the same slug (URL and backup filename)."""

    def __init__(self, slug: str) -> None:
        super().__init__(
            f"A project with the slug {slug!r} already exists. Project names "
            "must be distinguishable after slugification.",
            details={"slug": slug},
        )


# -----------------------------------------------------------------------------
# Naming
# -----------------------------------------------------------------------------


def slugify(name: str) -> str:
    """Filesystem-safe, stable slug for the backup filename.

    Deliberately lossy and ASCII-only: this ends up in a filename that an
    ops person types on a shell. Uniqueness is enforced separately on the
    column, so a collision after slugification is reported rather than
    silently de-duplicated with a suffix — two projects called "Q4 2026" and
    "Q4-2026" should be renamed by a human, not guessed at.
    """
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or "project"


# -----------------------------------------------------------------------------
# Service
# -----------------------------------------------------------------------------


class ProjectService:
    """Project reads and the pre-start backup."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._db = db
        self._settings = settings or get_settings()

    async def list_projects(self) -> list[Project]:
        """Newest first."""
        result = await self._db.execute(select(Project).order_by(Project.started_at.desc()))
        return list(result.scalars().all())

    async def get_project(self, project_id: uuid.UUID) -> Project | None:
        result = await self._db.execute(select(Project).where(Project.id == project_id))
        return result.scalars().one_or_none()

    async def project_counts(self) -> dict[uuid.UUID, dict[str, int]]:
        """Rows per project and table, across every project (unscoped)."""
        out: dict[uuid.UUID, dict[str, int]] = {}
        for label, model in COUNTED.items():
            rows = await self._db.execute(
                select(model.project_id, func.count()).group_by(model.project_id),
                execution_options={ALL_PROJECTS: True},
            )
            for project_id, count in rows.all():
                out.setdefault(project_id, {})[label] = int(count)
        return out

    def backup_problem(self) -> str | None:
        return self._backup_problem()

    def _backup_problem(self) -> str | None:
        """Why pg_dump could not run, or None.

        Checked in preflight so the operator is told before typing a
        confirmation, and again at execution time so a directory that
        disappeared in between still cannot produce an unbacked Start.
        """
        if shutil.which(self._settings.project_pg_dump_path) is None and not Path(
            self._settings.project_pg_dump_path
        ).is_file():
            return f"{self._settings.project_pg_dump_path!r} not found on PATH"

        backup_dir = Path(self._settings.project_backup_dir)
        if not backup_dir.is_dir():
            return f"backup directory {backup_dir} does not exist"
        if not os.access(backup_dir, os.W_OK):
            return f"backup directory {backup_dir} is not writable"
        if self._settings.project_backup_require_mount and not _on_mounted_volume(backup_dir):
            return (
                f"backup directory {backup_dir} is not a mounted volume: the dump would "
                "fill the root disk and be lost on the next deploy (see DEPLOYMENT.md)"
            )
        return None

    async def run_backup(self, slug: str, *, now: datetime | None = None) -> Path:
        """pg_dump the whole database to a custom-format file, and verify it.

        Custom format (-Fc) so a later restore can be selective rather than
        replaying a whole SQL script into a live database.

        Verified by listing the archive's table of contents with
        `pg_restore -l`. A dump that cannot be listed is not a backup, and
        finding that out now is the entire point of doing it first.
        """
        problem = self._backup_problem()
        if problem:
            raise BackupUnavailableError(problem)

        stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
        target = Path(self._settings.project_backup_dir) / f"project-{slug}-{stamp}.dump"

        dsn = self._dump_dsn()
        cmd = [
            self._settings.project_pg_dump_path,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            f"--file={target}",
            dsn,
        ]

        logger.info("Starting pre-start pg_dump", target=str(target))
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._settings.project_backup_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            target.unlink(missing_ok=True)
            raise BackupFailedError(
                f"pg_dump exceeded {self._settings.project_backup_timeout_seconds}s"
            ) from exc

        if process.returncode != 0:
            detail = stderr.decode("utf-8", "replace").strip()[:500]
            target.unlink(missing_ok=True)
            raise BackupFailedError(f"pg_dump exited {process.returncode}: {detail}")

        if not target.exists() or target.stat().st_size == 0:
            target.unlink(missing_ok=True)
            raise BackupFailedError("pg_dump produced no output")

        await self._verify_dump(target)
        logger.info(
            "Pre-start backup written",
            target=str(target),
            size_bytes=target.stat().st_size,
        )
        self.prune_backups(keep=target)
        return target

    async def verify_existing(self, path: str | Path) -> bool:
        """Is a dump recorded earlier (by a job now retried) still a good backup?"""
        target = Path(path)
        if not target.is_file() or target.stat().st_size == 0:
            return False
        try:
            await self._verify_dump(target)
        except BackupFailedError:
            return False
        return True

    def prune_backups(self, *, keep: Path | None = None) -> list[Path]:
        """Delete pre-start dumps beyond the newest `project_backup_keep`.

        Only `project-*.dump` files directly in the backup directory, newest
        first by modification time. `keep` (the dump just written) is never
        deleted. Hand-made dumps and other files are never touched. A file
        that cannot be deleted is logged and left; pruning never fails a
        Start.
        """
        backup_dir = Path(self._settings.project_backup_dir)
        limit = self._settings.project_backup_keep
        dumps = sorted(
            (p for p in backup_dir.glob("project-*.dump") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        removed: list[Path] = []
        for old in dumps[limit:]:
            if keep is not None and old.resolve() == keep.resolve():
                continue
            try:
                old.unlink()
                removed.append(old)
            except OSError as exc:
                logger.warning("Could not delete old pre-start dump", path=str(old), error=str(exc))
        if removed:
            logger.info("Old pre-start dumps deleted", kept=limit, removed=[p.name for p in removed])
        return removed

    async def _verify_dump(self, target: Path) -> None:
        """Confirm the dump is a readable archive, not truncated bytes."""
        restore = str(
            Path(self._settings.project_pg_dump_path).with_name("pg_restore")
        ) if os.sep in self._settings.project_pg_dump_path else "pg_restore"
        if shutil.which(restore) is None and not Path(restore).is_file():
            # Not fatal: the dump exists and is non-empty. Say so loudly
            # rather than deleting a good backup over a missing tool.
            logger.warning(
                "pg_restore not available; dump written but not verified",
                target=str(target),
            )
            return

        process = await asyncio.create_subprocess_exec(
            restore,
            "--list",
            str(target),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", "replace").strip()[:500]
            target.unlink(missing_ok=True)
            raise BackupFailedError(f"dump failed verification: {detail}")

    def _dump_dsn(self) -> str:
        """The app's DSN with the async driver stripped.

        SQLAlchemy carries `postgresql+asyncpg://`; libpq rejects the driver
        suffix. Everything else (host, port, user, password, database) is
        reused verbatim so the dump can never target a different database
        than the one the backend uses.
        """
        return str(self._settings.database_url).replace("+asyncpg", "", 1)


def _on_mounted_volume(path: Path) -> bool:
    """Is `path` on a mount below the container's root (a bind or named volume)?"""
    current = path.resolve()
    while current != current.parent:
        if os.path.ismount(current):
            return True
        current = current.parent
    return False
