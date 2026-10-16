#!/usr/bin/env python3
"""Start a new project, or restore an archived one, from the command line.

Same ProjectService the admin API uses — one implementation, so the CLI
cannot drift from the button. What the CLI has that the button does not:

  --dry-run         measure and report, change nothing
  --stop-streams    stop live inference first (the API requires the operator
                    to tick a box; here it is an explicit flag)
  --restore BATCH   put an archived batch back, which is deliberately not
                    exposed over HTTP

Usage:

    # What would happen?
    python -m scripts.start_new_project --dry-run

    # Do it (prompts for the confirmation unless --confirm-name is given)
    python -m scripts.start_new_project --name "Campaign 2026-Q4"

    # Non-interactive, e.g. from a runbook
    python -m scripts.start_new_project \
        --name "Campaign 2026-Q4" --confirm-name "Campaign 2026-Q4" \
        --stop-streams

    # List what has been archived
    python -m scripts.start_new_project --list

    # Put a batch back (live tables must be empty)
    python -m scripts.start_new_project --restore 3366a374-...

Exit codes: 0 success, 1 refused (preflight/confirmation), 2 operational
failure (backup, database).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# Allow `python scripts/start_new_project.py` as well as `-m`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.services.project_service import (  # noqa: E402
    BackupFailedError,
    BackupUnavailableError,
    ProjectError,
    ProjectService,
    StopInferenceTimeoutError,
    slugify,
)

REFUSED = 1
FAILED = 2


def _fmt_counts(counts: dict[str, int]) -> str:
    return "\n".join(f"    {t:<20} {c:>10,}" for t, c in counts.items())


async def _session_factory():
    settings = get_settings()
    engine = create_async_engine(str(settings.database_url))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def cmd_list() -> int:
    engine, factory = await _session_factory()
    try:
        async with factory() as db:
            for project in await ProjectService(db).list_projects():
                marker = "*" if project.state == "active" else " "
                span = project.started_at.date().isoformat()
                if project.ended_at:
                    span += f" .. {project.ended_at.date().isoformat()}"
                total = sum((project.archived_counts or {}).values())
                print(f"{marker} {project.name}")
                print(f"    state     {project.state}")
                print(f"    span      {span}")
                print(f"    by        {project.started_by}")
                if project.archive_batch_id:
                    print(f"    batch     {project.archive_batch_id}")
                    print(f"    archived  {total:,} rows")
                if project.backup_path:
                    print(f"    backup    {project.backup_path}")
                print()
    finally:
        await engine.dispose()
    return 0


async def cmd_dry_run(stop_streams: bool) -> int:
    engine, factory = await _session_factory()
    try:
        async with factory() as db:
            pre = await ProjectService(db).preflight(
                allow_stop_inference=stop_streams
            )
            current = pre.current_project.name if pre.current_project else "(none yet)"
            print(f"Current project:   {current}")
            print(f"Backup directory:  {pre.backup_dir}")
            print("Would archive:")
            print(_fmt_counts(pre.row_counts))
            print(f"    {'TOTAL':<20} {pre.total_rows:>10,}")
            print(
                f"\nEvidence rows holding VAS media ids: "
                f"{pre.evidence_with_vas_media:,}"
            )
            if pre.live_cameras:
                print(f"\nLive inference on {len(pre.live_cameras)} camera(s):")
                for camera in pre.live_cameras:
                    print(f"    {camera.camera_name}  ({camera.state})")
            if pre.blockers:
                print(f"\nBLOCKED: {', '.join(pre.blockers)}")
                return REFUSED
            print("\nPreflight clean; the archive would proceed.")
    finally:
        await engine.dispose()
    return 0


async def cmd_restore(batch_id: uuid.UUID, assume_yes: bool) -> int:
    engine, factory = await _session_factory()
    try:
        async with factory() as db:
            service = ProjectService(db)
            if not assume_yes:
                answer = input(
                    f"Restore batch {batch_id} into the live tables? [y/N] "
                )
                if answer.strip().lower() not in ("y", "yes"):
                    print("Aborted.")
                    return REFUSED
            try:
                restored = await service.restore_batch(batch_id)
                await db.commit()
            except ProjectError as exc:
                await db.rollback()
                print(f"Refused: {exc.message}", file=sys.stderr)
                return REFUSED
            print("Restored:")
            print(_fmt_counts(restored))
    finally:
        await engine.dispose()
    return 0


async def cmd_start(args: argparse.Namespace) -> int:
    engine, factory = await _session_factory()
    try:
        async with factory() as db:
            service = ProjectService(db)

            pre = await service.preflight(allow_stop_inference=args.stop_streams)
            print("Will archive:")
            print(_fmt_counts(pre.row_counts))
            print(f"    {'TOTAL':<20} {pre.total_rows:>10,}")

            if "backup_unavailable" in pre.blockers and not args.skip_backup:
                print(
                    f"\nCannot back up to {pre.backup_dir}. Fix that, or pass "
                    "--skip-backup --i-have-my-own-backup.",
                    file=sys.stderr,
                )
                return REFUSED
            if "inference_active" in pre.blockers:
                print(
                    f"\nInference is live on {len(pre.live_cameras)} camera(s): "
                    + ", ".join(c.camera_name for c in pre.live_cameras)
                    + "\nPass --stop-streams to stop them first.",
                    file=sys.stderr,
                )
                return REFUSED
            if "too_much_data" in pre.blockers and not args.confirm_large:
                print(
                    f"\n{pre.total_rows:,} rows exceeds the single-transaction "
                    "ceiling. Re-run with --confirm-large if you have "
                    "considered lock duration and WAL volume.",
                    file=sys.stderr,
                )
                return REFUSED

            confirm = args.confirm_name
            if confirm is None:
                confirm = input("\nRetype the new project name to confirm: ")
            if confirm != args.name:
                print("Confirmation did not match. Nothing was done.", file=sys.stderr)
                return REFUSED

            if args.stop_streams and pre.live_cameras:
                try:
                    stopped = await service.stop_all_inference(_StreamServiceShim(db))
                except StopInferenceTimeoutError as exc:
                    print(f"\n{exc.message}", file=sys.stderr)
                    return REFUSED
                print(f"Stopped inference on: {', '.join(stopped)}")

            backup_path = None
            if not args.skip_backup:
                try:
                    backup_path = await service.run_backup(slugify(args.name))
                    print(f"Backup written: {backup_path}")
                except (BackupUnavailableError, BackupFailedError) as exc:
                    print(f"\n{exc.message}", file=sys.stderr)
                    return FAILED
            else:
                print("Backup SKIPPED at operator request.")

            try:
                result = await service.start_new_project(
                    name=args.name,
                    confirm_name=confirm,
                    started_by=args.started_by,
                    backup_path=backup_path,
                )
                await db.commit()
            except ProjectError as exc:
                await db.rollback()
                print(
                    f"\nRefused: {exc.message}\n"
                    "The database was rolled back; nothing was archived.",
                    file=sys.stderr,
                )
                return REFUSED

            print(f"\nArchived {sum(result.counts.values()):,} rows from "
                  f"{result.archived_project.name!r}")
            print(f"Batch:   {result.archive_batch_id}")
            print(f"Started: {result.new_project.name!r}")
            print(
                f"VAS media paths: {result.vas_paths_resolved:,} resolved, "
                f"{result.vas_paths_missing:,} already gone from VAS"
            )
            print("\nNothing was deleted. No file on disk was moved.")
    finally:
        await engine.dispose()
    return 0


class _StreamServiceShim:
    """Minimal stand-in for StreamService.stop_inference.

    The real StreamService wants VAS and AI-runtime clients it does not need
    for this one call — stop-inference is documented as purely local (it ends
    the session row and the InferenceLoop notices). Reproducing that one
    behaviour here keeps the CLI free of the whole dependency graph; the
    service's own wait-for-terminal loop still verifies the outcome.
    """

    def __init__(self, db) -> None:
        self._db = db

    async def stop_inference(self, device_id) -> None:
        from datetime import datetime, timezone

        from sqlalchemy import update

        from app.models import StreamSession, StreamState

        await self._db.execute(
            update(StreamSession)
            .where(
                StreamSession.device_id == device_id,
                StreamSession.state.in_(
                    [StreamState.STARTING, StreamState.LIVE, StreamState.STOPPING]
                ),
            )
            .values(state=StreamState.STOPPED, stopped_at=datetime.now(timezone.utc))
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start a new project (archives the current one's data).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--name", help="Name of the new project")
    parser.add_argument(
        "--confirm-name",
        help="Retyped name. Omit to be prompted interactively.",
    )
    parser.add_argument(
        "--started-by",
        default="cli",
        help="Recorded on the project row as who did this (default: cli)",
    )
    parser.add_argument(
        "--stop-streams",
        action="store_true",
        help="Stop live inference first and wait for it to wind down",
    )
    parser.add_argument(
        "--confirm-large",
        action="store_true",
        help="Proceed despite an unusually large row count",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Do not run pg_dump (requires --i-have-my-own-backup)",
    )
    parser.add_argument(
        "--i-have-my-own-backup",
        action="store_true",
        help="Acknowledge that --skip-backup leaves no recovery point here",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Measure and report; change nothing",
    )
    parser.add_argument("--list", action="store_true", help="List projects")
    parser.add_argument(
        "--restore",
        metavar="BATCH_ID",
        help="Restore an archive batch into the (empty) live tables",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip the interactive restore prompt"
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        return asyncio.run(cmd_list())
    if args.dry_run:
        return asyncio.run(cmd_dry_run(args.stop_streams))
    if args.restore:
        try:
            batch = uuid.UUID(args.restore)
        except ValueError:
            parser.error(f"--restore expects a UUID, got {args.restore!r}")
        return asyncio.run(cmd_restore(batch, args.yes))

    if not args.name:
        parser.error("--name is required (or use --dry-run / --list / --restore)")
    if len(args.name.strip()) < 3:
        parser.error("--name must be at least 3 characters")
    if args.skip_backup and not args.i_have_my_own_backup:
        parser.error(
            "--skip-backup requires --i-have-my-own-backup. Archiving without "
            "a recovery point is a decision that should be stated explicitly."
        )

    args.name = args.name.strip()
    return asyncio.run(cmd_start(args))


if __name__ == "__main__":
    raise SystemExit(main())
