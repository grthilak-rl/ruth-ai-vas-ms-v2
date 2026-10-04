"""enforce one active stream session per device (partial unique index)

The service layer already allows only one active (starting / live /
stopping) session per device: start-inference returns the existing session,
and StreamService.start_stream refuses with StreamAlreadyActiveError. But the
check and the insert are separate statements, and nothing in the database
backs the rule, so two concurrent starts can both insert. That happened
twice in production history (ppe_detection started twice, 1s and 6s apart;
the first pair then ran duplicate inference for ~24h).

This index makes the database enforce the rule the code already assumes. The
losing insert of a race now fails, and start_stream maps that to the existing
StreamAlreadyActiveError -> 409.

Adds one index; changes no table, column, type or row. Upgrade refuses to run
(with the offending rows listed) if any device currently has more than one
active session, rather than guessing which to keep. Downgrade drops only the
index.

Revision ID: stream_sessions_one_active
Revises: add_model_store
Create Date: 2026-10-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "stream_sessions_one_active"
down_revision: Union[str, None] = "add_model_store"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_stream_sessions_device_active"
ACTIVE_STATES_SQL = "state IN ('starting', 'live', 'stopping')"


def upgrade() -> None:
    """Create the partial unique index, after checking it can hold."""
    duplicates = op.get_bind().execute(
        sa.text(
            f"""
            SELECT device_id,
                   string_agg(id::text || ' ' || model_id || ' ' || state::text, '; ') AS sessions
            FROM stream_sessions
            WHERE {ACTIVE_STATES_SQL}
            GROUP BY device_id
            HAVING count(*) > 1
            """
        )
    ).fetchall()
    if duplicates:
        listing = "\n".join(f"  device {row.device_id}: {row.sessions}" for row in duplicates)
        raise RuntimeError(
            "Cannot enforce one active stream session per device: these devices "
            "currently have more than one active session. Stop the extra "
            "session(s) (stop-inference) and re-run the migration.\n" + listing
        )

    op.create_index(
        INDEX_NAME,
        "stream_sessions",
        ["device_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_STATES_SQL),
    )


def downgrade() -> None:
    """Drop only the index created above."""
    op.drop_index(INDEX_NAME, table_name="stream_sessions")
