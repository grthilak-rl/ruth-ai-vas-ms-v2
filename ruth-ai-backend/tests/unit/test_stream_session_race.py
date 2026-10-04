"""start_stream: a lost insert race maps to StreamAlreadyActiveError (409).

DB-free. The real race against Postgres and the partial unique index is in
tests/stream_sessions/.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.exceptions import StreamAlreadyActiveError
from app.services.stream_service import StreamService


def _service(flush_error: Exception) -> tuple[StreamService, MagicMock]:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock(side_effect=flush_error)
    db.rollback = AsyncMock()
    vas = MagicMock()
    vas.start_stream = AsyncMock()
    service = StreamService(vas, db)
    service._get_device = AsyncMock(return_value=SimpleNamespace(vas_device_id="vas-1"))
    return service, db


async def test_unique_index_violation_becomes_already_active():
    device_id, winner_id = uuid4(), uuid4()
    error = IntegrityError(
        "INSERT INTO stream_sessions ...",
        {},
        Exception('duplicate key value violates unique constraint "uq_stream_sessions_device_active"'),
    )
    service, db = _service(error)
    # First lookup (pre-insert check) finds nothing; after rollback, the winner.
    service._get_active_session = AsyncMock(side_effect=[None, SimpleNamespace(id=winner_id)])

    with pytest.raises(StreamAlreadyActiveError) as raised:
        await service.start_stream(device_id, model_id="ppe_detection")

    assert raised.value.details["session_id"] == str(winner_id)
    db.rollback.assert_awaited_once()
    service._vas.start_stream.assert_not_called()  # the loser never touches VAS


async def test_other_integrity_errors_still_raise():
    error = IntegrityError(
        "INSERT INTO stream_sessions ...",
        {},
        Exception('insert or update violates foreign key constraint "stream_sessions_device_id_fkey"'),
    )
    service, db = _service(error)
    service._get_active_session = AsyncMock(return_value=None)

    with pytest.raises(IntegrityError):
        await service.start_stream(uuid4())
    db.rollback.assert_not_awaited()
