"""Shift schedule API schemas.

The request/response envelope for the shift endpoints. The schedule's own
shape (`ShiftSchedule`, `ShiftDefinition`) is defined alongside the
algorithm in `app.services.shift_schedule` and re-exported here, so the
validation rules that the algorithm depends on cannot drift away from the
ones the API enforces.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.services.shift_schedule import ShiftDefinition, ShiftSchedule

__all__ = [
    "ShiftDefinition",
    "ShiftSchedule",
    "ShiftScheduleResponse",
    "ShiftScheduleUpdateRequest",
    "CurrentShiftResponse",
    "ShiftViolationCountsResponse",
]


class ShiftScheduleResponse(ShiftSchedule):
    """The stored site schedule (or the continuous default)."""

    #: False when no schedule row exists and the continuous default is
    #: being reported, so the config UI can distinguish "the site chose
    #: continuous" from "nobody has configured this yet".
    is_configured: bool = Field(
        default=False,
        description="Whether a schedule has been explicitly saved",
    )


class ShiftScheduleUpdateRequest(ShiftSchedule):
    """A proposed site schedule.

    Rejected with 422 if the shifts overlap or fail to cover 24 hours.
    """

    updated_by: str | None = Field(
        default=None,
        max_length=255,
        description="Operator making the change, for the audit trail",
    )


class CurrentShiftResponse(BaseModel):
    """The shift window containing the server's current instant."""

    name: str = Field(..., description='Shift name, or "Continuous"')
    start: datetime = Field(..., description="Window start (inclusive, UTC)")
    end: datetime = Field(..., description="Window end (exclusive, UTC)")
    mode: str = Field(..., description="continuous | shifts")
    timezone: str = Field(..., description="IANA timezone the window was computed in")
    server_time: datetime = Field(
        ...,
        description="Server instant used, so clients can detect clock skew",
    )


class ShiftViolationCountsResponse(BaseModel):
    """Per-camera unreviewed violation counts for the current shift."""

    shift: CurrentShiftResponse = Field(
        ...,
        description="The window the counts were taken over",
    )
    counts: dict[uuid.UUID, int] = Field(
        ...,
        description="camera_id -> unreviewed violations created this shift",
    )
