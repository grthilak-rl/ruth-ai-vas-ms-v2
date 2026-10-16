"""Start a new project: archive the current one's data, begin collecting fresh.

What "starts at zero" means here
--------------------------------
Nothing in this product stores a total. The 116,941 on the Open Alerts card
is `SELECT count(*) FROM violations WHERE status='open'` with no time bound,
evaluated on every poll; analytics, the shift badges, the exports and the
NLP chatbot's generated SQL are all live aggregates over the same five
tables. So there is no counter to reset. Moving the rows out *is* the reset,
and it is the only approach that also covers readers nobody can enumerate —
specifically the text-to-SQL chatbot, which writes its own
`SELECT count(*) FROM violations` and cannot be taught to filter.

Shape of the operation
----------------------
1. Preflight, all-or-nothing: refuse on live inference, on a name that does
   not match its confirmation, on a missing/unwritable backup directory, on
   a missing pg_dump. Each returns a distinct error the API maps to 409/422.
2. pg_dump, outside the transaction. Verified before anything is written.
3. One transaction, guarded by a session advisory lock: capture VAS media
   paths, copy all five tables into their archives, delete in FK-safe order,
   close the outgoing project row, open the new one.

A crash at any point before commit leaves the database exactly as it was.
The only residue is an orphan dump file, which is logged and harmless.

Why the whole thing fits in one transaction: measured 2026-10-16, the live
data is ~234k rows / ~150 MB (violations 116 953, evidence 116 937, events
13 318, sessions 79, analyses 0). That is seconds of work and a few hundred
MB of WAL. `preflight` re-measures every time and refuses above
MAX_UNBATCHED_ROWS rather than silently starting a long-running transaction
on a database that has grown by an order of magnitude.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.integrations.vas import VASClient, VASError
from app.models import (
    PROJECT_START_LOCK_KEY,
    PROJECT_STATE_ACTIVE,
    PROJECT_STATE_ARCHIVED,
    Device,
    Evidence,
    Project,
    StreamSession,
    StreamState,
)
from app.services.exceptions import ServiceError

logger = get_logger(__name__)

#: Session states that mean a writer is active. Identical to the set behind
#: `uq_stream_sessions_device_active` — archiving a session in one of these
#: states would also leave that device unable to start a new one, because the
#: partial unique index would still see the archived-away row's slot as free
#: while the InferenceLoop believed otherwise.
LIVE_STATES = (StreamState.STARTING, StreamState.LIVE, StreamState.STOPPING)

#: Above this, refuse the single-transaction archive and say so. Set well
#: above today's ~234k so it is a tripwire for unexpected growth, not a
#: routine obstacle.
MAX_UNBATCHED_ROWS = 5_000_000

#: VAS caps a media-paths lookup at 1000 ids per call.
VAS_PATH_CHUNK = 1000

#: How long to wait for a stopped session to reach a terminal state when the
#: caller opted into stopping inference.
STOP_WAIT_TIMEOUT = 30.0
STOP_POLL_INTERVAL = 0.5

LIVE_TABLES = ("violations", "events", "evidence", "stream_sessions", "bookmark_analyses")

#: Restore plan: (live table, live columns, archive SELECT expressions).
#:
#: Insert order is the exact reverse of the delete order — parents before the
#: children that reference them, or the FKs reject the rows. `devices` is
#: never archived, so the device_id references are satisfied by rows that
#: were there all along.
#:
#: The casts matter: the archive stores enums as text precisely so it cannot
#: be invalidated by an enum value being added or removed, which means coming
#: back requires casting into the live enum type. A value removed from the
#: enum since archiving will fail here — loudly, inside a transaction, rather
#: than by writing a row nobody can read.
_RESTORE_ORDER: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "stream_sessions",
        (
            "id", "device_id", "vas_stream_id", "model_id", "model_version",
            "inference_fps", "confidence_threshold", "model_config", "models",
            "models_revision", "state", "started_at", "stopped_at",
            "error_message", "frames_processed", "events_count",
            "violations_count", "created_at", "updated_at",
        ),
        (
            "id", "device_id", "vas_stream_id", "model_id", "model_version",
            "inference_fps", "confidence_threshold", "model_config", "models",
            "models_revision", "state::stream_state", "started_at",
            "stopped_at", "error_message", "frames_processed", "events_count",
            "violations_count", "created_at", "updated_at",
        ),
    ),
    (
        "violations",
        (
            "id", "device_id", "stream_session_id", "type", "type_detail",
            "status", "confidence", "timestamp", "camera_name", "model_id",
            "model_version", "bounding_boxes", "reviewed_by", "reviewed_at",
            "resolution_notes", "created_at", "updated_at",
        ),
        (
            "id", "device_id", "stream_session_id", "type::violation_type",
            "type_detail", "status::violation_status", "confidence",
            "timestamp", "camera_name", "model_id", "model_version",
            "bounding_boxes", "reviewed_by", "reviewed_at",
            "resolution_notes", "created_at", "updated_at",
        ),
    ),
    (
        "events",
        (
            "id", "device_id", "stream_session_id", "violation_id",
            "event_type", "confidence", "timestamp", "model_id",
            "model_version", "bounding_boxes", "frame_id",
            "inference_time_ms", "created_at", "updated_at",
        ),
        (
            "id", "device_id", "stream_session_id", "violation_id",
            "event_type::event_type", "confidence", "timestamp", "model_id",
            "model_version", "bounding_boxes", "frame_id",
            "inference_time_ms", "created_at", "updated_at",
        ),
    ),
    (
        "evidence",
        (
            "id", "violation_id", "evidence_type", "status",
            "vas_snapshot_id", "vas_bookmark_id",
            "bookmark_duration_seconds", "requested_at", "ready_at",
            "error_message", "retry_count", "last_retry_at", "created_at",
            "updated_at",
        ),
        (
            "id", "violation_id", "evidence_type::evidence_type",
            "status::evidence_status", "vas_snapshot_id", "vas_bookmark_id",
            "bookmark_duration_seconds", "requested_at", "ready_at",
            "error_message", "retry_count", "last_retry_at", "created_at",
            "updated_at",
        ),
    ),
    (
        "bookmark_analyses",
        (
            "id", "vas_bookmark_id", "model_id", "model_version",
            "parameters", "state", "summary", "error_message", "created_at",
            "started_at", "completed_at", "submitted_by",
        ),
        (
            "id", "vas_bookmark_id", "model_id", "model_version",
            "parameters", "state::bookmark_analysis_state", "summary",
            "error_message", "created_at", "started_at", "completed_at",
            "submitted_by",
        ),
    ),
)


# -----------------------------------------------------------------------------
# Errors
# -----------------------------------------------------------------------------


class ProjectError(ServiceError):
    """Base for project lifecycle errors."""


class InferenceActiveError(ProjectError):
    """Inference is running; archiving would race the writer.

    Carries the camera names so the operator can act without going hunting.
    """

    def __init__(self, cameras: list[dict[str, str]]) -> None:
        names = ", ".join(c["camera_name"] for c in cameras) or "unknown"
        super().__init__(
            f"Inference is live on {len(cameras)} camera(s): {names}. "
            "Stop inference first, or re-submit with stop_inference=true.",
            details={"cameras": cameras},
        )
        self.cameras = cameras


class ConfirmationMismatchError(ProjectError):
    """The retyped project name did not match."""

    def __init__(self) -> None:
        super().__init__(
            "The confirmation text does not match the project name exactly."
        )


class BackupUnavailableError(ProjectError):
    """pg_dump cannot run, so the archive must not start."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"Cannot take the pre-archive backup: {reason}. "
            "Refusing to archive without one.",
            details={"reason": reason},
        )


class BackupFailedError(ProjectError):
    """pg_dump ran but did not produce a usable dump."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Pre-archive backup failed: {reason}", details={"reason": reason})


class TooMuchDataError(ProjectError):
    """More rows than this one-transaction archiver is willing to move."""

    def __init__(self, total: int) -> None:
        super().__init__(
            f"{total:,} rows is above the {MAX_UNBATCHED_ROWS:,}-row ceiling for "
            "a single-transaction archive. Archive from the CLI, which can be "
            "supervised, or raise MAX_UNBATCHED_ROWS deliberately after "
            "considering lock duration and WAL volume.",
            details={"total_rows": total, "ceiling": MAX_UNBATCHED_ROWS},
        )


class ProjectNameInUseError(ProjectError):
    """Two projects would claim the same backup filename."""

    def __init__(self, slug: str) -> None:
        super().__init__(
            f"A project with the slug {slug!r} already exists. Project names "
            "must be distinguishable after slugification.",
            details={"slug": slug},
        )


class StopInferenceTimeoutError(ProjectError):
    """Sessions were asked to stop but did not reach a terminal state."""

    def __init__(self, cameras: list[str]) -> None:
        super().__init__(
            "These cameras did not stop within "
            f"{STOP_WAIT_TIMEOUT:.0f}s: {', '.join(cameras)}. Nothing was "
            "archived.",
            details={"cameras": cameras},
        )


# -----------------------------------------------------------------------------
# Value objects
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class LiveCamera:
    device_id: uuid.UUID
    camera_name: str
    session_id: uuid.UUID
    state: str

    def as_dict(self) -> dict[str, str]:
        return {
            "device_id": str(self.device_id),
            "camera_name": self.camera_name,
            "session_id": str(self.session_id),
            "state": self.state,
        }


@dataclass
class Preflight:
    """Everything the caller needs to decide, and everything that blocks.

    `blockers` is empty when the archive can proceed. The API renders this
    verbatim on the confirmation screen so the numbers the operator confirms
    are the numbers that were measured, not an estimate.
    """

    current_project: Project | None
    row_counts: dict[str, int]
    total_rows: int
    live_cameras: list[LiveCamera] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    backup_dir: str = ""
    evidence_with_vas_media: int = 0

    @property
    def can_proceed(self) -> bool:
        return not self.blockers


@dataclass
class ArchiveResult:
    archived_project: Project | None
    new_project: Project
    archive_batch_id: uuid.UUID | None
    counts: dict[str, int]
    backup_path: str | None
    vas_paths_resolved: int
    vas_paths_missing: int


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
    """Reads and writes the project lifecycle.

    The archive runs as one transaction on the caller's session. The caller
    (API endpoint or CLI) owns commit/rollback, which is what makes a crash
    mid-archive a clean no-op.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        vas_client: VASClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._db = db
        self._vas = vas_client
        self._settings = settings or get_settings()

    # -------------------------------------------------------------------------
    # Reads
    # -------------------------------------------------------------------------

    async def get_active_project(self) -> Project | None:
        result = await self._db.execute(
            select(Project).where(Project.state == PROJECT_STATE_ACTIVE)
        )
        return result.scalars().one_or_none()

    async def list_projects(self) -> list[Project]:
        """Newest first. Active project sorts first because it has no end."""
        result = await self._db.execute(
            select(Project).order_by(Project.started_at.desc())
        )
        return list(result.scalars().all())

    async def get_project(self, project_id: uuid.UUID) -> Project | None:
        result = await self._db.execute(select(Project).where(Project.id == project_id))
        return result.scalars().one_or_none()

    async def row_counts(self) -> dict[str, int]:
        """Count every table the archive will move.

        Five separate counts rather than one query: they are each a cheap
        index-only scan, and keeping them separate means the numbers shown
        to the operator are labelled by table without any parsing.
        """
        counts: dict[str, int] = {}
        for table in LIVE_TABLES:
            result = await self._db.execute(text(f"SELECT count(*) FROM {table}"))
            counts[table] = int(result.scalar() or 0)
        return counts

    async def live_cameras(self) -> list[LiveCamera]:
        """Sessions with a live writer, with their camera names resolved."""
        result = await self._db.execute(
            select(StreamSession, Device.name, Device.display_name)
            .join(Device, StreamSession.device_id == Device.id)
            .where(StreamSession.state.in_(LIVE_STATES))
            .order_by(Device.name)
        )
        return [
            LiveCamera(
                device_id=session.device_id,
                camera_name=display_name or name,
                session_id=session.id,
                state=session.state.value,
            )
            for session, name, display_name in result.all()
        ]

    # -------------------------------------------------------------------------
    # Preflight
    # -------------------------------------------------------------------------

    async def preflight(self, *, allow_stop_inference: bool = False) -> Preflight:
        """Measure and validate. Never mutates anything.

        `allow_stop_inference` only changes whether live cameras count as a
        blocker — it does not stop anything. The caller stops them explicitly
        so that "I asked for this" is recorded at the call site.
        """
        current = await self.get_active_project()
        counts = await self.row_counts()
        total = sum(counts.values())
        cameras = await self.live_cameras()

        blockers: list[str] = []
        if cameras and not allow_stop_inference:
            blockers.append("inference_active")
        if total > MAX_UNBATCHED_ROWS:
            blockers.append("too_much_data")

        backup_problem = self._backup_problem()
        if backup_problem:
            blockers.append("backup_unavailable")

        evidence_with_media = await self._db.execute(
            select(func.count())
            .select_from(Evidence)
            .where(
                (Evidence.vas_snapshot_id.is_not(None))
                | (Evidence.vas_bookmark_id.is_not(None))
            )
        )

        return Preflight(
            current_project=current,
            row_counts=counts,
            total_rows=total,
            live_cameras=cameras,
            blockers=blockers,
            backup_dir=self._settings.project_backup_dir,
            evidence_with_vas_media=int(evidence_with_media.scalar() or 0),
        )

    def _backup_problem(self) -> str | None:
        """Why pg_dump could not run, or None.

        Checked in preflight so the operator is told before typing a
        confirmation, and again at execution time so a directory that
        disappeared in between still cannot produce an unbacked archive.
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
        return None

    # -------------------------------------------------------------------------
    # Stopping inference
    # -------------------------------------------------------------------------

    async def stop_all_inference(self, stream_service) -> list[str]:
        """Stop every live session and wait for it to leave the live states.

        Returns the camera names that were stopped. Raises
        StopInferenceTimeoutError if any session is still live afterwards —
        archiving a camera whose InferenceLoop task has not actually wound
        down would copy rows while new ones were still arriving.

        The commit between stopping and waiting is deliberate: the
        InferenceLoop observes session state through its own session, so it
        cannot see a state change that is still uncommitted.
        """
        cameras = await self.live_cameras()
        if not cameras:
            return []

        for camera in cameras:
            try:
                await stream_service.stop_inference(camera.device_id)
            except Exception as exc:  # noqa: BLE001 - best effort, verified below
                logger.warning(
                    "stop_inference raised while preparing to archive",
                    device_id=str(camera.device_id),
                    camera=camera.camera_name,
                    error=str(exc),
                )
        await self._db.commit()

        deadline = asyncio.get_running_loop().time() + STOP_WAIT_TIMEOUT
        while True:
            still_live = await self.live_cameras()
            if not still_live:
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise StopInferenceTimeoutError([c.camera_name for c in still_live])
            await asyncio.sleep(STOP_POLL_INTERVAL)

        stopped = [c.camera_name for c in cameras]
        logger.info("Stopped inference before archiving", cameras=stopped)
        return stopped

    # -------------------------------------------------------------------------
    # Backup
    # -------------------------------------------------------------------------

    async def run_backup(self, slug: str, *, now: datetime | None = None) -> Path:
        """pg_dump the whole database to a custom-format file, and verify it.

        Custom format (-Fc) so a later restore can be selective: recovering
        one archived project means `pg_restore -t violations_archive`, not
        replaying a 150 MB SQL script into a live database.

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

        logger.info("Starting pre-archive pg_dump", target=str(target))
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
            "Pre-archive backup written",
            target=str(target),
            size_bytes=target.stat().st_size,
        )
        return target

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
        than the one being archived.
        """
        return str(self._settings.database_url).replace("+asyncpg", "", 1)

    # -------------------------------------------------------------------------
    # Archive
    # -------------------------------------------------------------------------

    async def start_new_project(
        self,
        *,
        name: str,
        confirm_name: str,
        started_by: str,
        backup_path: Path | None,
        skip_backup_record: bool = False,
    ) -> ArchiveResult:
        """Archive the active project's data and open `name`.

        Runs entirely inside the caller's transaction. `backup_path` is the
        dump already taken and verified by `run_backup` — this method does
        not take it, so the backup can happen outside the transaction where a
        failure costs nothing.

        Raises:
            ConfirmationMismatchError: confirm_name != name.
            ProjectNameInUseError: slug already taken.
            InferenceActiveError: a live session appeared since preflight.
            TooMuchDataError: row count above the single-transaction ceiling.
        """
        if confirm_name != name:
            raise ConfirmationMismatchError()

        name = name.strip()
        slug = slugify(name)

        # Serialise concurrent starts. A session-level lock (not xact) so it
        # is explicitly released below rather than depending on who commits.
        await self._db.execute(
            text("SELECT pg_advisory_lock(:key)"), {"key": PROJECT_START_LOCK_KEY}
        )
        try:
            return await self._start_new_project_locked(
                name=name,
                slug=slug,
                started_by=started_by,
                backup_path=backup_path,
                skip_backup_record=skip_backup_record,
            )
        finally:
            await self._db.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": PROJECT_START_LOCK_KEY},
            )

    async def _start_new_project_locked(
        self,
        *,
        name: str,
        slug: str,
        started_by: str,
        backup_path: Path | None,
        skip_backup_record: bool,
    ) -> ArchiveResult:
        existing = await self._db.execute(select(Project.id).where(Project.slug == slug))
        if existing.scalars().first() is not None:
            raise ProjectNameInUseError(slug)

        # Re-check under the lock: preflight ran before the operator typed
        # the confirmation, and a camera can have been started since.
        cameras = await self.live_cameras()
        if cameras:
            raise InferenceActiveError([c.as_dict() for c in cameras])

        counts = await self.row_counts()
        total = sum(counts.values())
        if total > MAX_UNBATCHED_ROWS:
            raise TooMuchDataError(total)

        now = datetime.now(timezone.utc)
        outgoing = await self.get_active_project()
        if outgoing is None:
            # First run. The rows already in the database belong to a project
            # that predates this feature; give it a real row so the history
            # is complete and the archive is attributable to something.
            outgoing = await self._synthesise_initial_project(now)

        batch_id = uuid.uuid4()
        vas_resolved, vas_missing = 0, 0

        if total:
            vas_resolved, vas_missing = await self._copy_all(
                batch_id=batch_id, project_id=outgoing.id
            )
            await self._delete_all()
        else:
            logger.info("Nothing to archive; opening the new project only")

        outgoing.state = PROJECT_STATE_ARCHIVED
        outgoing.ended_at = now
        outgoing.ended_by = started_by
        outgoing.archive_batch_id = batch_id if total else None
        outgoing.archived_counts = counts
        if not skip_backup_record:
            outgoing.backup_path = str(backup_path) if backup_path else None

        new_project = Project(
            name=name,
            slug=slug,
            state=PROJECT_STATE_ACTIVE,
            started_at=now,
            started_by=started_by,
        )
        self._db.add(new_project)
        await self._db.flush()

        logger.info(
            "Project started",
            project=name,
            project_id=str(new_project.id),
            started_by=started_by,
            archived_project=outgoing.name,
            archive_batch_id=str(batch_id) if total else None,
            archived_counts=counts,
            backup_path=str(backup_path) if backup_path else None,
            vas_paths_resolved=vas_resolved,
            vas_paths_missing=vas_missing,
        )

        return ArchiveResult(
            archived_project=outgoing,
            new_project=new_project,
            archive_batch_id=batch_id if total else None,
            counts=counts,
            backup_path=str(backup_path) if backup_path else None,
            vas_paths_resolved=vas_resolved,
            vas_paths_missing=vas_missing,
        )

    async def _synthesise_initial_project(self, now: datetime) -> Project:
        """A row for the data that existed before projects did.

        started_at is the oldest violation (or event) timestamp rather than
        `now`, so the archived project's date range describes the data it
        actually contains.
        """
        oldest = await self._db.execute(
            text(
                "SELECT least("
                "  (SELECT min(timestamp) FROM violations),"
                "  (SELECT min(timestamp) FROM events)"
                ")"
            )
        )
        started_at = oldest.scalar() or now

        project = Project(
            name="Initial data (before projects)",
            slug="initial-data",
            state=PROJECT_STATE_ACTIVE,
            started_at=started_at,
            started_by="system",
        )
        self._db.add(project)
        await self._db.flush()
        logger.info(
            "Synthesised the pre-projects baseline",
            project_id=str(project.id),
            started_at=started_at.isoformat(),
        )
        return project

    # -------------------------------------------------------------------------
    # Copy / delete
    # -------------------------------------------------------------------------

    async def _copy_all(
        self, *, batch_id: uuid.UUID, project_id: uuid.UUID
    ) -> tuple[int, int]:
        """Copy all five tables into their archives, then verify the counts.

        Column lists are written out explicitly rather than `SELECT *`: a
        column added to a live table should make this fail loudly at review
        or test time, not silently archive a row missing a field.

        Enum columns are cast to text — the archive must not depend on an
        enum type whose values change as models ship.
        """
        params = {"batch": str(batch_id), "project": str(project_id)}
        vas_resolved, vas_missing = await self._capture_vas_paths()

        await self._db.execute(
            text(
                """
                INSERT INTO violations_archive (
                    id, device_id, stream_session_id, type, type_detail, status,
                    confidence, timestamp, camera_name, model_id, model_version,
                    bounding_boxes, reviewed_by, reviewed_at, resolution_notes,
                    created_at, updated_at, archive_batch_id, project_id
                )
                SELECT
                    id, device_id, stream_session_id, type::text, type_detail,
                    status::text, confidence, timestamp, camera_name, model_id,
                    model_version, bounding_boxes, reviewed_by, reviewed_at,
                    resolution_notes, created_at, updated_at,
                    CAST(:batch AS uuid), CAST(:project AS uuid)
                FROM violations
                """
            ),
            params,
        )

        await self._db.execute(
            text(
                """
                INSERT INTO events_archive (
                    id, device_id, stream_session_id, violation_id, event_type,
                    confidence, timestamp, model_id, model_version,
                    bounding_boxes, frame_id, inference_time_ms,
                    created_at, updated_at, archive_batch_id, project_id
                )
                SELECT
                    id, device_id, stream_session_id, violation_id,
                    event_type::text, confidence, timestamp, model_id,
                    model_version, bounding_boxes, frame_id, inference_time_ms,
                    created_at, updated_at,
                    CAST(:batch AS uuid), CAST(:project AS uuid)
                FROM events
                """
            ),
            params,
        )

        # evidence_archive's vas_* path columns were already written into the
        # temp table by _capture_vas_paths; join them in here so the paths and
        # the row land together.
        await self._db.execute(
            text(
                """
                INSERT INTO evidence_archive (
                    id, violation_id, evidence_type, status, vas_snapshot_id,
                    vas_bookmark_id, bookmark_duration_seconds, requested_at,
                    ready_at, error_message, retry_count, last_retry_at,
                    created_at, updated_at,
                    vas_file_path, vas_video_file_path, vas_thumbnail_path,
                    vas_file_size, vas_paths_resolved,
                    archive_batch_id, project_id
                )
                SELECT
                    e.id, e.violation_id, e.evidence_type::text, e.status::text,
                    e.vas_snapshot_id, e.vas_bookmark_id,
                    e.bookmark_duration_seconds, e.requested_at, e.ready_at,
                    e.error_message, e.retry_count, e.last_retry_at,
                    e.created_at, e.updated_at,
                    p.file_path, p.video_file_path, p.thumbnail_path,
                    p.file_size, (p.evidence_id IS NOT NULL),
                    CAST(:batch AS uuid), CAST(:project AS uuid)
                FROM evidence e
                LEFT JOIN _vas_media_paths p ON p.evidence_id = e.id
                """
            ),
            params,
        )

        await self._db.execute(
            text(
                """
                INSERT INTO stream_sessions_archive (
                    id, device_id, vas_stream_id, model_id, model_version,
                    inference_fps, confidence_threshold, model_config, models,
                    models_revision, state, started_at, stopped_at,
                    error_message, frames_processed, events_count,
                    violations_count, created_at, updated_at,
                    archive_batch_id, project_id
                )
                SELECT
                    id, device_id, vas_stream_id, model_id, model_version,
                    inference_fps, confidence_threshold, model_config, models,
                    models_revision, state::text, started_at, stopped_at,
                    error_message, frames_processed, events_count,
                    violations_count, created_at, updated_at,
                    CAST(:batch AS uuid), CAST(:project AS uuid)
                FROM stream_sessions
                """
            ),
            params,
        )

        await self._db.execute(
            text(
                """
                INSERT INTO bookmark_analyses_archive (
                    id, vas_bookmark_id, model_id, model_version, parameters,
                    state, summary, error_message, created_at, started_at,
                    completed_at, submitted_by, archive_batch_id, project_id
                )
                SELECT
                    id, vas_bookmark_id, model_id, model_version, parameters,
                    state::text, summary, error_message, created_at,
                    started_at, completed_at, submitted_by,
                    CAST(:batch AS uuid), CAST(:project AS uuid)
                FROM bookmark_analyses
                """
            ),
            params,
        )

        await self._verify_copy(batch_id)
        return vas_resolved, vas_missing

    async def _verify_copy(self, batch_id: uuid.UUID) -> None:
        """Assert every live row has an archived twin, before deleting any.

        This is the one check that must not be skipped: the next statement
        deletes the originals. A mismatch raises, the transaction rolls back,
        and the live data is untouched.
        """
        pairs = (
            ("violations", "violations_archive"),
            ("events", "events_archive"),
            ("evidence", "evidence_archive"),
            ("stream_sessions", "stream_sessions_archive"),
            ("bookmark_analyses", "bookmark_analyses_archive"),
        )
        for live, archive in pairs:
            live_count = (
                await self._db.execute(text(f"SELECT count(*) FROM {live}"))
            ).scalar() or 0
            archived = (
                await self._db.execute(
                    text(f"SELECT count(*) FROM {archive} WHERE archive_batch_id = :b"),
                    {"b": str(batch_id)},
                )
            ).scalar() or 0
            if live_count != archived:
                raise ProjectError(
                    f"Archive verification failed for {live}: {live_count} live "
                    f"rows but {archived} archived. Nothing has been deleted; "
                    "the transaction will roll back.",
                    details={"table": live, "live": live_count, "archived": archived},
                )

    async def _delete_all(self) -> None:
        """Empty the live tables, in the only order that preserves the archive.

        The FKs are asymmetric and that dictates this order:

          events.violation_id       ON DELETE SET NULL
          events.stream_session_id  ON DELETE SET NULL
          evidence.violation_id     ON DELETE CASCADE
          violations.stream_session_id ON DELETE SET NULL

        Deleting violations before events would blank `events.violation_id`
        on rows still in the live table; deleting violations before evidence
        would cascade evidence away. Copying already happened, so the archive
        is safe either way — but the live tables must still be emptied
        without tripping a constraint, and doing it in dependency order also
        means no cascade fires at all, which keeps the statement counts
        honest.

        TRUNCATE would be faster but takes an ACCESS EXCLUSIVE lock and
        cannot be used on a table referenced by a FK from a non-truncated
        table without CASCADE — which would silently reach into tables this
        operation has no business emptying (`devices`). DELETE is the right
        tool at 234k rows.
        """
        for table in ("events", "evidence", "violations", "stream_sessions", "bookmark_analyses"):
            await self._db.execute(text(f"DELETE FROM {table}"))

    # -------------------------------------------------------------------------
    # Restore
    # -------------------------------------------------------------------------

    async def restore_batch(self, batch_id: uuid.UUID) -> dict[str, int]:
        """Move one archive batch back into the live tables.

        Deliberately not exposed on the HTTP API. Restoring 117k violations
        into whatever project is currently running is a supervised operation
        with a judgement call attached ("do you actually want the old site's
        alerts back on this dashboard?"), not something that should sit one
        click away from the archive button. It lives on the CLI, which the
        ops runbook reaches for.

        Insert order is the reverse of the delete order: the parents
        (`stream_sessions`, `violations`) must exist before the children
        (`events`, `evidence`) point at them, or the FKs reject the rows.

        Refuses unless the live tables are empty. Merging an archived project
        into a running one would produce a dashboard describing two
        different periods at once, and there is no way to un-merge it.

        Returns the per-table restored counts.
        """
        counts = await self.row_counts()
        non_empty = {t: c for t, c in counts.items() if c}
        if non_empty:
            raise ProjectError(
                "Refusing to restore into non-empty live tables: "
                + ", ".join(f"{t}={c}" for t, c in non_empty.items())
                + ". Archive the current project first.",
                details={"live_counts": non_empty},
            )

        params = {"batch": str(batch_id)}
        restored: dict[str, int] = {}

        for table, columns, selects in _RESTORE_ORDER:
            result = await self._db.execute(
                text(
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"SELECT {', '.join(selects)} FROM {table}_archive "
                    "WHERE archive_batch_id = CAST(:batch AS uuid)"
                ),
                params,
            )
            restored[table] = result.rowcount or 0

        # The archive rows stay. A restore is "also put it back", not "move
        # it back" — the batch remains the record of what was archived, and a
        # second restore is prevented by the empty-tables check above.
        project = await self._db.execute(
            select(Project).where(Project.archive_batch_id == batch_id)
        )
        found = project.scalars().one_or_none()
        logger.info(
            "Restored archive batch",
            batch_id=str(batch_id),
            project=found.name if found else None,
            restored=restored,
        )
        return restored

    # -------------------------------------------------------------------------
    # VAS media paths
    # -------------------------------------------------------------------------

    async def _capture_vas_paths(self) -> tuple[int, int]:
        """Record where VAS keeps each evidence file, while it still knows.

        Ruth stores no media paths: Evidence holds a VAS id and media is
        served by proxying to VAS. VAS's `media_cleanup_service` deletes the
        file *and* the row at retention, after which the id is dangling and
        unresolvable. Capturing paths now is the only moment they exist.

        Writes into a temp table (dropped at commit) that the evidence copy
        joins against, rather than updating 117k rows twice.

        Best-effort by design: VAS being unreachable must never block an
        archive. On failure every row gets NULL paths and
        `vas_paths_resolved = false`, which is a truthful record of "we did
        not find out" and is distinguishable from "VAS said it is gone".
        """
        await self._db.execute(
            text(
                """
                CREATE TEMPORARY TABLE _vas_media_paths (
                    evidence_id uuid PRIMARY KEY,
                    file_path text,
                    video_file_path text,
                    thumbnail_path text,
                    file_size bigint
                ) ON COMMIT DROP
                """
            )
        )

        if self._vas is None:
            logger.warning(
                "No VAS client available; archiving without media paths. "
                "Archived evidence will record vas_paths_resolved=false."
            )
            return 0, 0

        rows = (
            await self._db.execute(
                select(Evidence.id, Evidence.vas_snapshot_id, Evidence.vas_bookmark_id)
                .where(
                    (Evidence.vas_snapshot_id.is_not(None))
                    | (Evidence.vas_bookmark_id.is_not(None))
                )
            )
        ).all()
        if not rows:
            return 0, 0

        snapshot_owner: dict[str, list[uuid.UUID]] = {}
        bookmark_owner: dict[str, list[uuid.UUID]] = {}
        for evidence_id, snapshot_id, bookmark_id in rows:
            if snapshot_id:
                snapshot_owner.setdefault(snapshot_id, []).append(evidence_id)
            if bookmark_id:
                bookmark_owner.setdefault(bookmark_id, []).append(evidence_id)

        resolved: dict[uuid.UUID, dict[str, object]] = {}

        resolved_snapshots = await self._lookup_paths(
            list(snapshot_owner), self._vas.get_snapshot_paths
        )
        for snapshot_id, payload in resolved_snapshots.items():
            for evidence_id in snapshot_owner.get(snapshot_id, []):
                entry = resolved.setdefault(evidence_id, {})
                entry["file_path"] = payload.get("file_path")
                entry["file_size"] = payload.get("file_size")

        resolved_bookmarks = await self._lookup_paths(
            list(bookmark_owner), self._vas.get_bookmark_paths
        )
        for bookmark_id, payload in resolved_bookmarks.items():
            for evidence_id in bookmark_owner.get(bookmark_id, []):
                entry = resolved.setdefault(evidence_id, {})
                entry["video_file_path"] = payload.get("video_file_path")
                entry["thumbnail_path"] = payload.get("thumbnail_path")
                entry.setdefault("file_size", payload.get("file_size"))

        if resolved:
            await self._db.execute(
                text(
                    """
                    INSERT INTO _vas_media_paths
                        (evidence_id, file_path, video_file_path,
                         thumbnail_path, file_size)
                    VALUES (:evidence_id, :file_path, :video_file_path,
                            :thumbnail_path, :file_size)
                    ON CONFLICT (evidence_id) DO NOTHING
                    """
                ),
                [
                    {
                        "evidence_id": str(evidence_id),
                        "file_path": entry.get("file_path"),
                        "video_file_path": entry.get("video_file_path"),
                        "thumbnail_path": entry.get("thumbnail_path"),
                        "file_size": entry.get("file_size"),
                    }
                    for evidence_id, entry in resolved.items()
                ],
            )

        missing = len(rows) - len(resolved)
        logger.info(
            "Captured VAS media paths for archiving",
            evidence_with_media=len(rows),
            resolved=len(resolved),
            missing=missing,
        )
        return len(resolved), missing

    async def _lookup_paths(self, ids: list[str], fetch) -> dict[str, dict]:
        """Chunked lookup that degrades to {} rather than failing the archive."""
        if not ids:
            return {}
        out: dict[str, dict] = {}
        for start in range(0, len(ids), VAS_PATH_CHUNK):
            chunk = ids[start : start + VAS_PATH_CHUNK]
            try:
                out.update(await fetch(chunk))
            except (VASError, OSError) as exc:
                logger.warning(
                    "VAS media-path lookup failed for a chunk; those rows "
                    "will record vas_paths_resolved=false",
                    chunk_size=len(chunk),
                    error=str(exc),
                )
        return out
