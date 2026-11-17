"""A project lifecycle action (Start, Stop, End, Resume) run as a background job.

The request validates and returns a job id at once; the job runs its stages
in the backend and records each one, so the UI can poll it, a restart
leaves an honest "interrupted" row, and Retry continues from the recorded
stage. At most one job is queued or running (partial unique index).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"
JOB_INTERRUPTED = "interrupted"

JOB_STATES = (JOB_QUEUED, JOB_RUNNING, JOB_SUCCEEDED, JOB_FAILED, JOB_INTERRUPTED)
#: A job in one of these blocks every other lifecycle job.
JOB_ACTIVE_STATES = (JOB_QUEUED, JOB_RUNNING)
#: A job in one of these can be retried (if it is the latest job).
JOB_RETRYABLE_STATES = (JOB_FAILED, JOB_INTERRUPTED)

JOB_ACTIONS = ("start", "stop", "end", "resume", "cameras")


class ProjectJob(Base, TimestampMixin):
    __tablename__ = "project_jobs"
    __table_args__ = (
        Index(
            "uq_project_jobs_one_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("state IN ('queued', 'running')"),
        ),
        Index("ix_project_jobs_created_at", "created_at"),
        CheckConstraint(
            "action IN ('start', 'stop', 'end', 'resume', 'cameras')", name="ck_project_jobs_action"
        ),
        CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed', 'interrupted')",
            name="ck_project_jobs_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=JOB_QUEUED)

    #: The stage running now, or the one that failed / was interrupted.
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: One line about the stage, e.g. "DEMO-CAMERA2 (2/3)".
    stage_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: What was asked: name, confirm_name, camera_ids, allow_no_cameras.
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: Per-camera plan and per-camera errors of the last attempt.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Start: the verified dump, reused by Retry.
    backup_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The project acted on. Start: set in the same transaction that creates
    #: the project, so Retry never creates it twice.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", name="fk_project_jobs_project_id"), nullable=True
    )

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
