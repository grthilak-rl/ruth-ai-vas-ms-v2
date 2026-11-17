"""Camera membership with dates; "Change cameras" project action.

project_cameras becomes one row per membership interval:

- ``joined_at`` / ``left_at`` (NULL while the camera is still in the
  project). A camera can leave and rejoin: one open row per camera at most
  (``uq_project_cameras_open``).
- ``inferred``: dates reconstructed from data, not recorded when it happened.

Backfill:

- Rows picked in the Start dialog or added by hand: joined when added
  (never before the project started); left when the project ended.
- Rows derived from data (``source = 'derived'``, all of HPCL and Initial
  data): joined at the camera's first activity (stream session or
  violation) in the project; left at its last activity if that was more than
  a day before the project stopped/ended (removed mid-project), else when the
  project ended. Marked inferred.
- HPCL cameras 75089 and 75107 were added on 23 Oct but never ran inference,
  so no data shows them: added as inferred members from Ruth's first sight of
  them (devices.created_at, within minutes of VAS creating them) to HPCL's
  end. Skipped if either the project or the cameras are absent.

Also allows the "cameras" action on project_jobs.

No other table is touched; no VAS data (placements, location history) is
read or written.

Revision ID: project_camera_membership
Revises: project_jobs
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "project_camera_membership"
down_revision = "project_jobs"
branch_labels = None
depends_on = None

#: Cameras added to HPCL mid-project that left no data in Ruth.
HPCL_SILENT_ADDITIONS = ("75089", "75107")


def upgrade() -> None:
    op.add_column(
        "project_cameras",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=True,
                  server_default=sa.text("gen_random_uuid()")),
    )
    op.add_column("project_cameras", sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("project_cameras", sa.Column("left_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "project_cameras",
        sa.Column("inferred", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute("UPDATE project_cameras SET id = gen_random_uuid() WHERE id IS NULL")

    # Recorded memberships (dialog / manual).
    op.execute("""
        UPDATE project_cameras pc
           SET joined_at = GREATEST(p.started_at, pc.added_at),
               left_at = p.ended_at,
               inferred = false
          FROM projects p
         WHERE p.id = pc.project_id AND pc.source <> 'derived'
    """)

    # Derived memberships: dates from the camera's activity in the project.
    op.execute("""
        WITH activity AS (
            SELECT project_id, device_id, MIN(first_at) AS first_at, MAX(last_at) AS last_at
              FROM (
                    SELECT project_id, device_id, started_at AS first_at,
                           COALESCE(stopped_at, started_at) AS last_at
                      FROM stream_sessions WHERE started_at IS NOT NULL
                    UNION ALL
                    SELECT project_id, device_id, "timestamp", "timestamp" FROM violations
                   ) a
             GROUP BY project_id, device_id
        )
        UPDATE project_cameras pc
           SET joined_at = GREATEST(p.started_at, a.first_at),
               left_at = CASE
                   WHEN p.ended_at IS NULL THEN NULL
                   WHEN a.last_at >= COALESCE(p.stopped_at, p.ended_at) - interval '1 day' THEN p.ended_at
                   ELSE GREATEST(a.last_at, p.started_at, a.first_at)
               END,
               inferred = true
          FROM projects p, activity a
         WHERE p.id = pc.project_id AND pc.source = 'derived'
           AND a.project_id = pc.project_id AND a.device_id = pc.device_id
    """)
    # A derived row with no activity row at all (should not happen): whole project.
    op.execute("""
        UPDATE project_cameras pc
           SET joined_at = p.started_at, left_at = p.ended_at, inferred = true
          FROM projects p
         WHERE p.id = pc.project_id AND pc.joined_at IS NULL
    """)

    op.drop_constraint("project_cameras_pkey", "project_cameras", type_="primary")
    op.alter_column("project_cameras", "id", nullable=False)
    op.alter_column("project_cameras", "joined_at", nullable=False)
    op.create_primary_key("project_cameras_pkey", "project_cameras", ["id"])
    op.create_index(
        "uq_project_cameras_open", "project_cameras", ["project_id", "device_id"],
        unique=True, postgresql_where=sa.text("left_at IS NULL"),
    )
    op.create_index("ix_project_cameras_project_joined", "project_cameras", ["project_id", "joined_at"])
    op.create_check_constraint(
        "ck_project_cameras_interval", "project_cameras", "left_at IS NULL OR left_at >= joined_at"
    )

    # HPCL's two silent additions (see module docstring).
    names = ", ".join(f"'{n}'" for n in HPCL_SILENT_ADDITIONS)
    op.execute(f"""
        INSERT INTO project_cameras (id, project_id, device_id, source, added_at, joined_at, left_at, inferred)
        SELECT gen_random_uuid(), p.id, d.id, 'derived', now(),
               GREATEST(p.started_at, d.created_at), p.ended_at, true
          FROM projects p
          JOIN devices d ON d.name IN ({names})
         WHERE p.slug = 'hpcl' AND p.ended_at IS NOT NULL
           AND d.created_at BETWEEN p.started_at AND p.ended_at
           AND NOT EXISTS (
                SELECT 1 FROM project_cameras x WHERE x.project_id = p.id AND x.device_id = d.id)
    """)

    op.drop_constraint("ck_project_jobs_action", "project_jobs", type_="check")
    op.create_check_constraint(
        "ck_project_jobs_action", "project_jobs",
        "action IN ('start', 'stop', 'end', 'resume', 'cameras')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM project_jobs WHERE action = 'cameras'")
    op.drop_constraint("ck_project_jobs_action", "project_jobs", type_="check")
    op.create_check_constraint(
        "ck_project_jobs_action", "project_jobs", "action IN ('start', 'stop', 'end', 'resume')"
    )
    # Back to one row per (project, camera): keep the latest interval.
    op.execute("""
        DELETE FROM project_cameras pc USING project_cameras newer
         WHERE newer.project_id = pc.project_id AND newer.device_id = pc.device_id
           AND newer.joined_at > pc.joined_at
    """)
    op.drop_constraint("ck_project_cameras_interval", "project_cameras", type_="check")
    op.drop_index("ix_project_cameras_project_joined", "project_cameras")
    op.drop_index("uq_project_cameras_open", "project_cameras")
    op.drop_constraint("project_cameras_pkey", "project_cameras", type_="primary")
    op.create_primary_key("project_cameras_pkey", "project_cameras", ["project_id", "device_id"])
    for col in ("inferred", "left_at", "joined_at", "id"):
        op.drop_column("project_cameras", col)
