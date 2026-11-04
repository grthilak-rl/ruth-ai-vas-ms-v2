"""Auto reports cannot be duplicated, against a real migrated Postgres.

Runs the scheduler's own enqueue twice for the same shifts, as a restart or
a second scheduler would, and checks one row per shift occurrence. Manual
reports for the same period are not constrained. Needs
SCHEMA_TEST_DATABASE_URL (see test_project_states_schema.py); rolled back.
"""

import os
from datetime import date, datetime, timedelta, timezone

import pytest

URL = os.environ.get("SCHEMA_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="SCHEMA_TEST_DATABASE_URL not set")


async def test_enqueue_twice_keeps_one_row_per_shift():
    from sqlalchemy import func, select, text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.models.customer_report import CustomerReport
    from app.services.report.auto import AutoReportScheduler, due_occurrences
    from app.services.shift_schedule import ShiftDefinition, ShiftSchedule

    schedule = ShiftSchedule(mode="shifts", timezone="Asia/Kolkata", shifts=[
        ShiftDefinition(name="Shift 1", start="07:00", end="19:00"),
        ShiftDefinition(name="Shift 2", start="19:00", end="07:00"),
    ])
    now = datetime(2026, 11, 3, 2, 30, tzinfo=timezone.utc)
    due = due_occurrences(schedule, now, now - timedelta(days=2), timedelta(minutes=15))
    assert due

    engine = create_async_engine(URL)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                db = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
                sched = AutoReportScheduler()
                first = await sched._enqueue(db, due, now)
                # A second scheduler that has not seen the first's rows.
                await sched._enqueue(db, due, now)
                count = (
                    await db.execute(
                        select(func.count()).select_from(CustomerReport).where(
                            CustomerReport.trigger == "auto"
                        )
                    )
                ).scalar_one()
                assert first == len(due) and count == len(due)

                # Bypassing the Python check: the index still refuses.
                o = due[0]
                await conn.execute(text(
                    "INSERT INTO customer_reports (id, status, preset, mode, period_start, period_end, "
                    "period_label, trigger, created_at, updated_at) VALUES (gen_random_uuid(), "
                    "'building', 'shift', 'all', :s, :e, 'x', 'auto', now(), now()) ON CONFLICT DO NOTHING"
                ), {"s": o.start, "e": o.end})
                again = (await conn.execute(text(
                    "SELECT count(*) FROM customer_reports WHERE trigger='auto' AND period_start=:s"
                ), {"s": o.start})).scalar_one()
                assert again == 1

                # Manual reports for the same period are allowed.
                await conn.execute(text(
                    "INSERT INTO customer_reports (id, status, preset, mode, period_start, period_end, "
                    "period_label, trigger, created_at, updated_at) VALUES (gen_random_uuid(), "
                    "'building', 'shift', 'all', :s, :e, 'x', 'manual', now(), now())"
                ), {"s": o.start, "e": o.end})
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()
