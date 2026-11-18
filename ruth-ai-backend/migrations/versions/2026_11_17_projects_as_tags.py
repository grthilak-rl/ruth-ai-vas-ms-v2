"""Projects as tags: project_id on every detection-data row; archive copied back.

Until now starting a project MOVED the previous project's rows into the
``*_archive`` tables. From here on rows are tagged instead, and the portal
can be put into any project's context (app/core/project_scope.py).

What this does, in one transaction:

1. ``ruth_current_project_id()``: the project in a current state, else the
   most recently started one. It is the column default that tags new rows.
2. If there is no project at all (a fresh install), creates "Initial
   project" so new rows have something to be tagged with.
3. Adds ``project_id`` (nullable for now) to violations, events, evidence,
   stream_sessions, bookmark_analyses, customer_reports, violation_exports.
4. Tags the rows already in the live tables: detection data with the
   site's project (on a site that used Start, the live tables hold exactly
   the current project's data); evidence with its violation's project;
   reports and exports with the project whose period contains their
   created_at, else the site's project.
5. COPIES every archived row back into its live table, tagged with the
   project it was archived from (INSERT ... SELECT with enum casts, parents
   before children). The archive tables are NOT modified or emptied; a
   later release drops them. Verifies afterwards that every archived id is
   present in its live table, and refuses (rolls back) otherwise.
6. project_id becomes NOT NULL with the default, a foreign key to projects
   and an index; violations also get (project_id, timestamp).
7. ``project_cameras``: the cameras of each project. Backfilled from the
   cameras each project's violations and sessions came from ("derived").
8. Projects: ``ended`` stops being a current state (so the next project can
   start after End); the project archived by the old flow becomes ``ended``.

Restored violations have no location stamp (area / side / display name):
they resolve from the device at read time, exactly as archived rows did.
scripts/backfill_violation_locations.py can stamp them once the site has
confirmed the camera history.

Downgrade is refused: after upgrade, rows written or reviewed in any project
exist only in the tagged tables, and no automatic downgrade can put them
back where the old code expects without losing something. Roll back by
restoring the pg_dump taken before the upgrade (DEPLOYMENT.md).

Revision ID: projects_as_tags
Revises: violation_location_stamp
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "projects_as_tags"
down_revision = "violation_location_stamp"
branch_labels = None
depends_on = None

TAGGED = (
    "violations",
    "events",
    "evidence",
    "stream_sessions",
    "bookmark_analyses",
    "customer_reports",
    "violation_exports",
)

CURRENT_STATES = ("active", "stopping", "stopped", "resuming")
ALL_STATES = ("active", "stopping", "stopped", "resuming", "ended", "archived")

FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION ruth_current_project_id() RETURNS uuid
LANGUAGE plpgsql STABLE AS $fn$
BEGIN
    RETURN (
        SELECT id FROM projects
        ORDER BY (state IN ('active', 'stopping', 'stopped', 'resuming')) DESC,
                 started_at DESC
        LIMIT 1
    );
END
$fn$
"""

#: (live table, archive table, live columns, archive SELECT expressions).
#: Parents before children, or the foreign keys reject the rows. The archive
#: stores enums as text, so coming back casts into the live enum types.
RESTORE = (
    (
        "stream_sessions",
        "stream_sessions_archive",
        (
            "id", "device_id", "vas_stream_id", "model_id", "model_version",
            "inference_fps", "confidence_threshold", "model_config", "models",
            "models_revision", "state", "started_at", "stopped_at",
            "error_message", "frames_processed", "events_count",
            "violations_count", "created_at", "updated_at", "project_id",
        ),
        (
            "id", "device_id", "vas_stream_id", "model_id", "model_version",
            "inference_fps", "confidence_threshold", "model_config", "models",
            "models_revision", "state::stream_state", "started_at",
            "stopped_at", "error_message", "frames_processed", "events_count",
            "violations_count", "created_at", "updated_at", "project_id",
        ),
    ),
    (
        "violations",
        "violations_archive",
        (
            "id", "device_id", "stream_session_id", "type", "type_detail",
            "status", "confidence", "timestamp", "camera_name", "model_id",
            "model_version", "bounding_boxes", "reviewed_by", "reviewed_at",
            "resolution_notes", "severity", "dismiss_reason", "created_at",
            "updated_at", "project_id",
        ),
        (
            "id", "device_id", "stream_session_id", "type::violation_type",
            "type_detail", "status::violation_status", "confidence",
            "timestamp", "camera_name", "model_id", "model_version",
            "bounding_boxes", "reviewed_by", "reviewed_at",
            "resolution_notes", "severity", "dismiss_reason", "created_at",
            "updated_at", "project_id",
        ),
    ),
    (
        "events",
        "events_archive",
        (
            "id", "device_id", "stream_session_id", "violation_id",
            "event_type", "confidence", "timestamp", "model_id",
            "model_version", "bounding_boxes", "frame_id",
            "inference_time_ms", "created_at", "updated_at", "project_id",
        ),
        (
            "id", "device_id", "stream_session_id", "violation_id",
            "event_type::event_type", "confidence", "timestamp", "model_id",
            "model_version", "bounding_boxes", "frame_id",
            "inference_time_ms", "created_at", "updated_at", "project_id",
        ),
    ),
    (
        "evidence",
        "evidence_archive",
        (
            "id", "violation_id", "evidence_type", "status", "file_path",
            "vas_snapshot_id", "vas_bookmark_id", "bookmark_duration_seconds",
            "requested_at", "ready_at", "error_message", "retry_count",
            "last_retry_at", "created_at", "updated_at", "project_id",
        ),
        (
            "id", "violation_id", "evidence_type::evidence_type",
            "status::evidence_status", "file_path", "vas_snapshot_id",
            "vas_bookmark_id", "bookmark_duration_seconds", "requested_at",
            "ready_at", "error_message", "retry_count", "last_retry_at",
            "created_at", "updated_at", "project_id",
        ),
    ),
    (
        "bookmark_analyses",
        "bookmark_analyses_archive",
        (
            "id", "vas_bookmark_id", "model_id", "model_version", "parameters",
            "state", "summary", "error_message", "created_at", "started_at",
            "completed_at", "submitted_by", "project_id",
        ),
        (
            "id", "vas_bookmark_id", "model_id", "model_version", "parameters",
            "state::bookmark_analysis_state", "summary", "error_message",
            "created_at", "started_at", "completed_at", "submitted_by",
            "project_id",
        ),
    ),
)


def _in(states) -> str:
    return "state IN (" + ", ".join(f"'{s}'" for s in states) + ")"


def _log(message: str) -> None:
    print(f"[projects_as_tags] {message}", flush=True)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. The default.
    op.execute(FUNCTION_SQL)

    # 2. A project to tag with, on a fresh install.
    if not bind.execute(sa.text("SELECT count(*) FROM projects")).scalar():
        oldest = bind.execute(
            sa.text("SELECT least((SELECT min(timestamp) FROM violations), (SELECT min(timestamp) FROM events))")
        ).scalar()
        bind.execute(
            sa.text(
                "INSERT INTO projects (id, name, slug, state, started_at, started_by, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'Initial project', 'initial-project', 'active', "
                "coalesce(:oldest, now()), 'system', now(), now())"
            ),
            {"oldest": oldest},
        )
        _log("no projects: created 'Initial project'")

    site = bind.execute(sa.text("SELECT ruth_current_project_id()")).scalar()

    # 3. Columns, nullable while they are filled.
    for table in TAGGED:
        op.add_column(table, sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True))

    # 4. Tag what is already live.
    for table in ("violations", "events", "stream_sessions", "bookmark_analyses"):
        n = bind.execute(sa.text(f"UPDATE {table} SET project_id = :p"), {"p": site}).rowcount
        _log(f"tagged {n} live {table} rows with the site's project")
    n = bind.execute(
        sa.text(
            "UPDATE evidence e SET project_id = v.project_id FROM violations v WHERE v.id = e.violation_id"
        )
    ).rowcount
    _log(f"tagged {n} live evidence rows with their violation's project")
    for table in ("customer_reports", "violation_exports"):
        n = bind.execute(
            sa.text(
                f"""
                UPDATE {table} t SET project_id = coalesce(
                    (SELECT p.id FROM projects p
                      WHERE p.started_at <= t.created_at
                        AND (p.ended_at IS NULL OR t.created_at < p.ended_at)
                      ORDER BY p.started_at DESC LIMIT 1),
                    :p)
                """
            ),
            {"p": site},
        ).rowcount
        _log(f"tagged {n} {table} rows by created_at")

    # 5. Copy the archive back (the archive itself is left untouched).
    for live, archive, columns, exprs in RESTORE:
        n = bind.execute(
            sa.text(
                f"INSERT INTO {live} ({', '.join(columns)}) "
                f"SELECT {', '.join(exprs)} FROM {archive} a "
                f"WHERE NOT EXISTS (SELECT 1 FROM {live} l WHERE l.id = a.id)"
            )
        ).rowcount
        missing = bind.execute(
            sa.text(f"SELECT count(*) FROM {archive} a WHERE NOT EXISTS (SELECT 1 FROM {live} l WHERE l.id = a.id)")
        ).scalar()
        if missing:
            raise RuntimeError(f"{missing} rows of {archive} are not in {live} after the copy; rolled back")
        _log(f"copied {n} rows {archive} -> {live}")

    leftover = {
        t: bind.execute(sa.text(f"SELECT count(*) FROM {t} WHERE project_id IS NULL")).scalar()
        for t in TAGGED
    }
    leftover = {t: n for t, n in leftover.items() if n}
    if leftover:
        raise RuntimeError(f"untagged rows remain, rolled back: {leftover}")

    # 6. NOT NULL, default, FK, index.
    for table in TAGGED:
        op.alter_column(table, "project_id", nullable=False, server_default=sa.text("ruth_current_project_id()"))
        op.create_foreign_key(f"fk_{table}_project_id", table, "projects", ["project_id"], ["id"])
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])
    op.create_index("ix_violations_project_timestamp", "violations", ["project_id", "timestamp"])

    # 7. Cameras per project.
    op.create_table(
        "project_cameras",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "device_id"),
    )
    n = bind.execute(
        sa.text(
            """
            INSERT INTO project_cameras (project_id, device_id, source)
            SELECT DISTINCT project_id, device_id, 'derived' FROM (
                SELECT project_id, device_id FROM violations
                UNION SELECT project_id, device_id FROM stream_sessions
            ) d
            """
        )
    ).rowcount
    _log(f"derived {n} project cameras")

    # 8. Ended is past, not current.
    op.drop_index("uq_projects_one_current", table_name="projects")
    op.execute(f"CREATE UNIQUE INDEX uq_projects_one_current ON projects ((true)) WHERE {_in(CURRENT_STATES)}")
    n = bind.execute(sa.text("UPDATE projects SET state = 'ended', updated_at = now() WHERE state = 'archived'")).rowcount
    _log(f"{n} archived project(s) -> ended")


def downgrade() -> None:
    raise RuntimeError(
        "projects_as_tags cannot be downgraded automatically: rows written or "
        "reviewed since the upgrade exist only in the tagged live tables. Roll "
        "back by restoring the pg_dump taken before the upgrade (see "
        "vas-ruthai-deploy/DEPLOYMENT.md, 'Projects as tags')."
    )
