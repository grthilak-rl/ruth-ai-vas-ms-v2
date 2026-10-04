"""stream_sessions.models: several models on one camera's session

Adds two columns to stream_sessions:

- models JSONB NULL: list of {model_id, model_version, config, fps_override}.
  NULL means a legacy single-model session (model_id / model_config, exactly
  as before) and keeps running the original inference loop unchanged.
  When set, model_id / model_version / model_config mirror models[0], so
  every existing reader stays correct.
- models_revision INT NOT NULL DEFAULT 0: bumped on every change to the list
  or an entry; the inference loop restarts the session's task when it moves.

No backfill: existing rows keep models = NULL. Downgrade refuses while any
active session runs more than one model (dropping the column would silently
stop all but the first); otherwise it drops both columns.

Revision ID: stream_session_models
Revises: stream_sessions_one_active
Create Date: 2026-10-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "stream_session_models"
down_revision: Union[str, None] = "stream_sessions_one_active"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stream_sessions",
        sa.Column(
            "models",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Models run on this session; NULL = legacy single model_id",
        ),
    )
    op.add_column(
        "stream_sessions",
        sa.Column(
            "models_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Bumped on every change to models; triggers a task restart",
        ),
    )


def downgrade() -> None:
    multi = op.get_bind().execute(
        sa.text(
            """
            SELECT id, device_id, jsonb_array_length(models) AS n
            FROM stream_sessions
            WHERE state IN ('starting', 'live', 'stopping')
              AND models IS NOT NULL AND jsonb_array_length(models) > 1
            """
        )
    ).fetchall()
    if multi:
        listing = "\n".join(f"  session {r.id} (device {r.device_id}): {r.n} models" for r in multi)
        raise RuntimeError(
            "Cannot drop stream_sessions.models: these active sessions run more "
            "than one model. Remove models down to one (or stop the sessions) "
            "first.\n" + listing
        )
    op.drop_column("stream_sessions", "models_revision")
    op.drop_column("stream_sessions", "models")
