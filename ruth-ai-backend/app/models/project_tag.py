"""Projects as tags: every detection-data row says which project it belongs to.

A project is a label on rows, not a place rows are moved to. The tagged
tables are violations, events, evidence, stream_sessions,
bookmark_analyses, customer_reports and violation_exports.

Writing
-------
``project_id`` defaults, in the database, to ``ruth_current_project_id()``:
the project in a current state (active, stopping, stopped, resuming), or
failing that the most recently started one. Every live writer (inference
loop, event ingestion, evidence, sessions) is covered by the default without
code changes, and a writer nobody remembered cannot produce an untagged row.

Writes made *about a past project* (a report over HPCL, an export of HPCL
violations) must not rely on the default, which would tag them with the
current project. Those set ``project_id`` explicitly to the viewed project.

Reading
-------
See app/core/project_scope.py: a request's session carries the project it
is scoped to, and every ORM read of a tagged table is filtered by it.
"""

import uuid

from sqlalchemy import DDL, ForeignKey, event, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.models.base import Base

CURRENT_PROJECT_FUNCTION = "ruth_current_project_id"

#: plpgsql, not sql: a LANGUAGE sql body is validated at CREATE time, which
#: would fail when the function is created before the projects table (as
#: Base.metadata.create_all does in the DB-backed tests).
CREATE_CURRENT_PROJECT_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {CURRENT_PROJECT_FUNCTION}() RETURNS uuid
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

DROP_CURRENT_PROJECT_FUNCTION = f"DROP FUNCTION IF EXISTS {CURRENT_PROJECT_FUNCTION}()"

#: Tables carrying project_id, in no particular order.
TAGGED_TABLES = (
    "violations",
    "events",
    "evidence",
    "stream_sessions",
    "bookmark_analyses",
    "customer_reports",
    "violation_exports",
)

event.listen(
    Base.metadata,
    "before_create",
    DDL(CREATE_CURRENT_PROJECT_FUNCTION).execute_if(dialect="postgresql"),
)


class ProjectTagMixin:
    """Adds the project tag. NOT NULL; the database supplies the default.

    ``eager_defaults`` makes the INSERT return the defaulted project_id
    (RETURNING), so reading ``row.project_id`` after a flush does not need a
    lazy refresh, which an async session cannot do.
    """

    __mapper_args__ = {"eager_defaults": True}

    @declared_attr
    def project_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805 - declared_attr
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("projects.id", name=f"fk_{cls.__tablename__}_project_id"),
            nullable=False,
            index=True,
            server_default=text(f"{CURRENT_PROJECT_FUNCTION}()"),
        )
