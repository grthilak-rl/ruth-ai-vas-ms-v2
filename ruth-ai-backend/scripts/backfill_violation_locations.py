"""Backfill area / side / display name on violations written before
location stamping existed, from VAS's camera location history.

Run inside the Ruth backend container:

    python scripts/backfill_violation_locations.py report
    python scripts/backfill_violation_locations.py apply --confirmed 75129,75096 [--dry-run]
    python scripts/backfill_violation_locations.py apply --all-confirmed [--dry-run]

``report`` changes nothing: per camera, the unstamped violations, their time
range, and VAS's history for that camera (how many placements, whether any
is an unverified seed). VAS seeded each camera's history with its location
at deploy time, starting at the camera's creation; that start is an
ASSUMPTION. Confirm with the site which cameras moved during the project
and correct their history in VAS first (PUT /api/v1/devices/{id}/placements).

``apply`` stamps only rows with location_stamped_at IS NULL (never touches
stamped rows, so it is safe to re-run) and only for cameras whose history is
fully confirmed in VAS, plus the cameras named in --confirmed (= "the site
confirmed this camera did not move; its seeded history is right"), or all
cameras with --all-confirmed. A violation outside every placement window is
stamped with no area (the camera was not placed anywhere then).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.integrations.vas.client import VASClient  # noqa: E402
from app.integrations.vas.exceptions import VASNotFoundError  # noqa: E402
from app.models import Device, Violation  # noqa: E402
from app.services.violation_location import unverified, windows_from_placements  # noqa: E402


async def _context():
    settings = get_settings()
    engine = create_async_engine(str(settings.database_url))
    vas = VASClient(
        base_url=settings.vas_base_url,
        client_id=settings.vas_client_id,
        client_secret=settings.vas_client_secret,
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False), vas


async def _unstamped_by_device(db):
    rows = (
        await db.execute(
            select(
                Violation.device_id,
                func.count(),
                func.min(Violation.timestamp),
                func.max(Violation.timestamp),
            )
            .where(Violation.location_stamped_at.is_(None))
            .group_by(Violation.device_id)
        )
    ).all()
    devices = {
        d.id: d
        for d in (
            await db.execute(select(Device).where(Device.id.in_([r[0] for r in rows])))
        ).scalars()
    } if rows else {}
    return [(devices.get(r[0]), r[1], r[2], r[3]) for r in rows]


def _fmt(p: dict) -> str:
    end = p.get("valid_to") or "open"
    flag = "" if p.get("verified", p.get("source") != "seed") else "  [UNVERIFIED seed]"
    return f"{p.get('location') or '-'} {p.get('in_out') or '-'}  {p['valid_from']} .. {end}{flag}"


async def report(sessions, vas) -> int:
    async with sessions() as db:
        groups = await _unstamped_by_device(db)
    if not groups:
        print("No unstamped violations.")
        return 0
    print("Unstamped violations per camera, with VAS location history:\n")
    for device, n, first, last in sorted(groups, key=lambda g: g[0].name if g[0] else ""):
        name = device.name if device else "?"
        print(f"{name}: {n} violations, {first:%Y-%m-%d %H:%M} .. {last:%Y-%m-%d %H:%M} UTC")
        if device is None:
            print("    device missing in Ruth")
            continue
        try:
            history = await vas.get_placements(device.vas_device_id)
        except VASNotFoundError:
            print("    not in VAS (cannot backfill)")
            continue
        if not history:
            print("    no placements in VAS: violations would be stamped with no area")
        for p in history:
            print(f"    {_fmt(p)}")
        if history and first < datetime.fromisoformat(history[0]["valid_from"]):
            print("    ! violations exist before the first placement")
    return 0


async def apply(sessions, vas, confirmed: set[str], all_confirmed: bool, dry_run: bool) -> int:
    async with sessions() as db:
        groups = await _unstamped_by_device(db)
    skipped, total = [], 0
    now = datetime.now(timezone.utc)
    for device, n, _first, _last in groups:
        if device is None:
            continue
        try:
            history = await vas.get_placements(device.vas_device_id)
        except VASNotFoundError:
            skipped.append(f"{device.name} (not in VAS)")
            continue
        if unverified(history) and not (all_confirmed or device.name in confirmed):
            skipped.append(f"{device.name} (history not confirmed)")
            continue
        windows = windows_from_placements(history)
        async with sessions() as db:
            done = 0
            for start, end, stamp in windows:
                cond = [
                    Violation.device_id == device.id,
                    Violation.location_stamped_at.is_(None),
                    Violation.timestamp >= start,
                ]
                if end is not None:
                    cond.append(Violation.timestamp < end)
                res = await db.execute(
                    update(Violation)
                    .where(*cond)
                    .values(
                        area=stamp.area,
                        in_out=stamp.in_out,
                        camera_display_name=stamp.display_name or device.name,
                        location_source="backfill",
                        location_stamped_at=now,
                    )
                )
                done += res.rowcount or 0
            # Outside every window: not placed anywhere at that time.
            res = await db.execute(
                update(Violation)
                .where(
                    Violation.device_id == device.id,
                    Violation.location_stamped_at.is_(None),
                )
                .values(
                    area=None,
                    in_out=None,
                    camera_display_name=device.name,
                    location_source="backfill",
                    location_stamped_at=now,
                )
            )
            outside = res.rowcount or 0
            if dry_run:
                await db.rollback()
            else:
                await db.commit()
        total += done + outside
        print(f"{device.name}: {done} stamped from history, {outside} outside any placement")
    if skipped:
        print("\nSkipped:\n  " + "\n  ".join(skipped))
    print(f"\n{'Would stamp' if dry_run else 'Stamped'} {total} violations.")
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report")
    a = sub.add_parser("apply")
    a.add_argument("--confirmed", default="", help="comma-separated camera names confirmed by the site")
    a.add_argument("--all-confirmed", action="store_true", help="site confirmed every camera's history")
    a.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    engine, sessions, vas = await _context()
    await vas.connect()
    try:
        if args.cmd == "report":
            return await report(sessions, vas)
        confirmed = {c.strip() for c in args.confirmed.split(",") if c.strip()}
        return await apply(sessions, vas, confirmed, args.all_confirmed, args.dry_run)
    finally:
        await vas.close()
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
