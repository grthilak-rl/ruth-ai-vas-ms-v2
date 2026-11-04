"""'Select all matching' on the Violations page: POST /violations/bulk with a
filter, and the confidence buckets it (and the page) filter on."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.v1 import violations as violations_api
from app.models import Violation, ViolationStatus
from app.models.confidence_levels import (
    HIGH_FROM,
    MEDIUM_FROM,
    confidence_condition,
    confidence_label,
    confidence_level,
)
from app.schemas import ViolationBulkRequest
from app.schemas.violation import BULK_LIMIT, ViolationResponse
from app.services.violation_service import ViolationService

UNTIL = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
SINCE = UNTIL - timedelta(days=7)


def row(status=ViolationStatus.OPEN):
    return SimpleNamespace(
        id=uuid.uuid4(), status=status, reviewed_by=None, reviewed_at=None,
        resolution_notes=None, dismiss_reason=None,
    )


class Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)

    def scalar(self):
        return self._rows


def fake_db(*results):
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[Rows(r) for r in results])
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def by_filter(expected, **filter_over):
    flt = {"since": SINCE.isoformat(), "until": UNTIL.isoformat(), **filter_over}
    return ViolationBulkRequest(filter=flt, expected_count=expected, action="review")


def sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def params(stmt) -> dict:
    return stmt.compile(dialect=postgresql.dialect()).params


# --------------------------------------------------------------------------
# Request shape
# --------------------------------------------------------------------------


def test_request_is_ids_or_filter_never_both():
    vid = uuid.uuid4()
    flt = {"until": UNTIL.isoformat()}
    with pytest.raises(ValidationError, match="either ids or filter"):
        ViolationBulkRequest(action="review")
    with pytest.raises(ValidationError, match="either ids or filter"):
        ViolationBulkRequest(ids=[vid], filter=flt, expected_count=1, action="review")
    with pytest.raises(ValidationError, match="expected_count is required"):
        ViolationBulkRequest(filter=flt, action="review")
    with pytest.raises(ValidationError, match="expected_count only applies"):
        ViolationBulkRequest(ids=[vid], expected_count=1, action="review")


def test_expected_count_is_capped():
    with pytest.raises(ValidationError):
        by_filter(BULK_LIMIT + 1)
    with pytest.raises(ValidationError):
        by_filter(0)
    assert by_filter(BULK_LIMIT).expected_count == BULK_LIMIT


def test_filter_range_must_be_frozen_and_absolute():
    # No until: a relative "last 7 days" would keep moving under the dialog.
    with pytest.raises(ValidationError, match="until"):
        ViolationBulkRequest(filter={"since": SINCE.isoformat()}, expected_count=1, action="review")
    # Naive timestamps are ambiguous across the browser/server time zones.
    with pytest.raises(ValidationError, match="time zone"):
        ViolationBulkRequest(filter={"until": "2026-11-04T12:00:00"}, expected_count=1, action="review")
    with pytest.raises(ValidationError, match="since must not be after until"):
        ViolationBulkRequest(
            filter={"since": UNTIL.isoformat(), "until": SINCE.isoformat()},
            expected_count=1, action="review",
        )
    with pytest.raises(ValidationError, match="confidences"):
        by_filter(1, confidences=["sure"])


def test_filter_has_no_status_field():
    # Status is not the caller's to choose: only open violations are matched.
    assert "statuses" not in by_filter(1).filter.model_dump()
    assert "status" not in by_filter(1).filter.model_dump()


# --------------------------------------------------------------------------
# Endpoint
# --------------------------------------------------------------------------


async def test_filter_changes_exactly_the_confirmed_set():
    a, b = row(), row()
    db = fake_db([a, b])
    response = await violations_api.bulk_update_violations(by_filter(2), ViolationService(db=None), db)
    assert response.updated == [a.id, b.id] and not response.skipped
    assert a.status == ViolationStatus.REVIEWED and b.status == ViolationStatus.REVIEWED
    db.commit.assert_awaited_once()


async def test_filter_query_forces_open_locks_rows_and_uses_the_frozen_range():
    db = fake_db([row()])
    await violations_api.bulk_update_violations(
        by_filter(1, severities=["critical"], confidences=["low"]), ViolationService(db=None), db
    )
    stmt = db.execute.await_args_list[0].args[0]
    text, bound = sql(stmt), params(stmt)

    assert "violations.status IN" in text
    assert [v for k, v in bound.items() if k.startswith("status")] == [[ViolationStatus.OPEN]]
    assert "FOR UPDATE" in text
    assert UNTIL in bound.values() and SINCE in bound.values()
    assert "violations.timestamp <=" in text and "violations.timestamp >=" in text
    assert "violations.confidence <" in text and MEDIUM_FROM in bound.values()
    assert "LIMIT" in text and (BULK_LIMIT + 1) in bound.values()


async def test_count_mismatch_is_409_and_changes_nothing():
    a, b, c = row(), row(), row()  # one more arrived / was un-dismissed since the dialog opened
    db = fake_db([a, b, c])
    with pytest.raises(HTTPException) as err:
        await violations_api.bulk_update_violations(by_filter(2), ViolationService(db=None), db)
    assert err.value.status_code == 409
    assert err.value.detail["error"] == "count_changed"
    assert err.value.detail["details"] == {"expected_count": 2, "current_count": 3}
    assert all(r.status == ViolationStatus.OPEN for r in (a, b, c))
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()


async def test_fewer_than_confirmed_is_also_409():
    db = fake_db([row()])
    with pytest.raises(HTTPException) as err:
        await violations_api.bulk_update_violations(by_filter(2), ViolationService(db=None), db)
    assert err.value.status_code == 409 and err.value.detail["details"]["current_count"] == 1
    db.commit.assert_not_awaited()


async def test_over_the_cap_is_422_with_the_real_count():
    rows = [row() for _ in range(BULK_LIMIT + 1)]
    db = fake_db(rows, 4321)  # the locked page, then the count query
    with pytest.raises(HTTPException) as err:
        await violations_api.bulk_update_violations(by_filter(BULK_LIMIT), ViolationService(db=None), db)
    assert err.value.status_code == 422
    assert err.value.detail["error"] == "too_many"
    assert err.value.detail["details"] == {"current_count": 4321, "limit": BULK_LIMIT}
    assert all(r.status == ViolationStatus.OPEN for r in rows)
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()
    # The count uses the same filters, open forced.
    count_stmt = db.execute.await_args_list[1].args[0]
    assert "violations.status IN" in sql(count_stmt)


async def test_unknown_family_is_422():
    db = fake_db([])
    with pytest.raises(HTTPException) as err:
        await violations_api.bulk_update_violations(
            by_filter(1, violation_type="nope"), ViolationService(db=None), db
        )
    assert err.value.status_code == 422 and not db.execute.await_count


async def test_ids_requests_are_unchanged():
    a = row()
    db = fake_db([a])
    response = await violations_api.bulk_update_violations(
        ViolationBulkRequest(ids=[a.id], action="review"), ViolationService(db=None), db
    )
    assert response.updated == [a.id]
    assert "FOR UPDATE" not in sql(db.execute.await_args.args[0])


# --------------------------------------------------------------------------
# Confidence buckets
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,level",
    [(None, "low"), (0.0, "low"), (0.5999, "low"), (MEDIUM_FROM, "medium"), (0.7999, "medium"),
     (HIGH_FROM, "high"), (1.0, "high")],
)
def test_confidence_level_cut_offs(value, level):
    assert confidence_level(value) == level
    assert confidence_label(value) == level.capitalize()


def test_confidence_condition_merges_adjacent_buckets():
    assert confidence_condition(Violation.confidence, []) is None
    assert confidence_condition(Violation.confidence, ["low", "medium", "high"]) is None

    def where(levels):
        return sql(select(Violation.id).where(confidence_condition(Violation.confidence, levels)))

    assert " OR " not in where(["high", "medium"])  # one range: >= MEDIUM_FROM
    assert "violations.confidence >=" in where(["high", "medium"])
    assert "violations.confidence <" not in where(["high", "medium"])
    assert " OR " in where(["high", "low"])  # two ranges


def test_apply_filters_rejects_unknown_bucket():
    with pytest.raises(HTTPException) as err:
        violations_api.apply_violation_filters(select(Violation.id), confidences=["certain"])
    assert err.value.status_code == 422


def test_responses_carry_the_bucket_not_just_the_number():
    now = datetime.now(UTC)
    body = ViolationResponse(
        id=uuid.uuid4(), type="ppe_violation", type_label="PPE", status="open",
        camera_id=uuid.uuid4(), camera_name="1", confidence=0.65, timestamp=now,
        model_id="m", model_version="1", created_at=now, updated_at=now,
    ).model_dump()
    assert body["confidence_level"] == "medium"
