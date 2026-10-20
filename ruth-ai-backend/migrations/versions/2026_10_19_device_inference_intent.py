"""Desired inference per camera, and backfill it from what is running.

BL-11 A. A camera's inference could stop — backend restart, VAS dropping
a stream, a session dying — and nothing recorded that anyone had asked
for it, so nothing could put it back. 74004 ran 21.3 hours that way.

The backfill is the important half. Without it every camera currently
running would be "never configured" at deploy, and the reconciler would
leave all twelve alone — technically correct, operationally useless. So
every camera with a live session becomes desired-active with exactly the
models it is running right now.

Revision ID: device_inference_intent
Revises: violation_dismiss_reason
"""

import sqlalchemy as sa
from alembic import op

revision = "device_inference_intent"
down_revision = "violation_dismiss_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_inference_intent",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "device_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("desired_state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("models", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("inference_fps", sa.Integer, nullable=True),
        sa.Column("confidence_threshold", sa.Float, nullable=True),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
    )
    op.create_index("ix_device_inference_intent_device_id", "device_inference_intent", ["device_id"])
    op.create_index("ix_intent_desired_state", "device_inference_intent", ["desired_state"])

    # Backfill from live sessions. `models` is copied verbatim so a resume
    # hands back exactly what is running; legacy single-model sessions
    # (models IS NULL) are converted to the list shape here, because the
    # reconciler should not have to know that two shapes ever existed.
    op.execute(
        """
        INSERT INTO device_inference_intent (
            id, device_id, desired_state, models, inference_fps,
            confidence_threshold, consecutive_failures, updated_at, updated_by
        )
        SELECT
            gen_random_uuid(),
            s.device_id,
            'active',
            COALESCE(
                s.models,
                jsonb_build_array(
                    jsonb_build_object(
                        'model_id', s.model_id,
                        'model_version', s.model_version,
                        'config', s.model_config,
                        'fps_override', NULL
                    )
                )
            ),
            s.inference_fps,
            s.confidence_threshold,
            0,
            NOW(),
            'migration-backfill'
        FROM stream_sessions s
        WHERE s.state = 'live'
          AND s.device_id IS NOT NULL
        ON CONFLICT (device_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_intent_desired_state", table_name="device_inference_intent")
    op.drop_index("ix_device_inference_intent_device_id", table_name="device_inference_intent")
    op.drop_table("device_inference_intent")
