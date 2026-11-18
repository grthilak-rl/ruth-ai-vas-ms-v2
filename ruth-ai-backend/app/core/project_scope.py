"""Which project a database session reads: the project view mode.

Every row of detection data is tagged with its project (app/models/
project_tag.py). A session can be *scoped* to one project; then every
ORM read of a tagged table through that session is filtered to that
project, by a ``do_orm_execute`` hook that adds ``with_loader_criteria``.
One mechanism instead of ~90 hand-written ``WHERE project_id = ...``: a
query site nobody remembered is still scoped, which is the failure that
matters (one project's numbers silently mixed into another's).

Which project a request reads
-----------------------------
Resolved once per request in ``get_db`` (app/deps/db.py):

* Paths under SCOPED_PATH_PREFIXES (Violations, Analytics, Reports,
  exports, events) read the project named by the ``X-Ruth-Project`` header
  (or ``?project=``; id or slug), defaulting to the current project.
* By-id paths below those prefixes (one violation, its frame, clip and
  snapshot; one report; one export) are not scoped: an id names one row
  and a link to it must open whichever project it belongs to. Their
  responses carry ``project_id`` so the UI can show that project's banner.
* Everything else (Cameras, live view, System Health, models, the AI
  runtime's internal endpoints) ignores the header and reads the current
  project. Live pages always show the current setup.

Background tasks
----------------
They open sessions from the session factory, never through get_db, so they
are unscoped (see every project) unless they scope themselves:

* inference loop, evidence capture, bookmark-analysis worker: unscoped;
  they work by id, and new rows are tagged by the database default.
* reconciler: unscoped; devices and intents are global, gated by site_state.
* VAS event consumer: no reads of tagged tables (it pauses/activates loops).
* auto-report scheduler: unscoped; tags each queued report explicitly with
  the current project and runs only while that project is active.
* export / report sweepers, clip-status sync: unscoped ON PURPOSE, so past
  projects' files still expire and their clips still finish.
* report build job: per row (scoped to the report's project).
* export build job: unscoped session, statement filtered to the export's
  project explicitly.
* event aggregation (ViolationService.get_open_violation) filters to the
  current project itself, so no session can fold a new detection into a
  past project's open violation.

tests/projects/test_background_scope.py pins the sweepers, clip sync and
aggregation.

Not covered, by design
----------------------
* Raw ``text()`` SQL. Today only project_service uses it, for whole-table
  maintenance. tests/unit/test_project_scope.py fails if a new raw query of
  a tagged table appears.
* Relationship loads (``selectinload(Violation.evidence)``): children are in
  their parent's project, and filtering them would break the unscoped by-id
  paths.
* Writes. The tag on a new row comes from the database default (the current
  project) or is set explicitly (past-project reports and exports).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.models import (
    CURRENT_PROJECT_STATES,
    BookmarkAnalysis,
    CustomerReport,
    Event,
    Evidence,
    Project,
    Violation,
    ViolationExport,
)

#: session.info key holding the scoped project's id.
SCOPE_KEY = "ruth_project_id"

#: Execution option that bypasses the scope for one statement, for the few
#: readers that must see every project (the project list's counts).
ALL_PROJECTS = "ruth_all_projects"

#: Filtered automatically. StreamSession is tagged but NOT auto-filtered:
#: sessions are live operational state, and the stream service must see a
#: stuck session whatever project it was started in, or the device's
#: one-active-session index would fail on insert instead of being handled.
#: Readers that want a project's sessions filter them explicitly.
SCOPED_MODELS = (Violation, Event, Evidence, BookmarkAnalysis, CustomerReport, ViolationExport)

#: Request paths that honour the view-mode header.
SCOPED_PATH_PREFIXES = (
    "/api/v1/violations",
    "/api/v1/analytics",
    "/api/v1/events",
    "/api/v1/admin/customer-reports",
    "/api/v1/admin/violation-exports",
)

HEADER = "X-Ruth-Project"
QUERY_PARAM = "project"

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_BY_ID = re.compile(
    r"^/api/v1/(violations|events|admin/customer-reports|admin/violation-exports)/" + _UUID + r"(/|$)"
)


def path_mode(path: str) -> str:
    """'by_id' (unscoped), 'scoped' (honours the header) or 'live' (current)."""
    if _BY_ID.match(path):
        return "by_id"
    if any(path == p or path.startswith(p + "/") for p in SCOPED_PATH_PREFIXES):
        return "scoped"
    return "live"


@dataclass(frozen=True)
class ProjectScope:
    """The project a request reads, as resolved by get_db."""

    project: Project | None
    #: True when the request reads the current project (no header, a live
    #: path, or the header names the current project).
    is_current: bool
    #: False for by-id paths: the session is not filtered.
    filtered: bool = True

    @property
    def project_id(self) -> uuid.UUID | None:
        return self.project.id if self.project else None


class UnknownProjectError(Exception):
    def __init__(self, ref: str) -> None:
        super().__init__(f"No project {ref!r}")
        self.ref = ref


# ---------------------------------------------------------------------------
# Session scoping
# ---------------------------------------------------------------------------


def scope_session(session: AsyncSession | Session, project_id: uuid.UUID | None) -> None:
    """Filter every ORM read of a tagged table through `session` to one project.

    None removes the scope (every project is visible).
    """
    target = session.sync_session if isinstance(session, AsyncSession) else session
    if project_id is None:
        target.info.pop(SCOPE_KEY, None)
    else:
        target.info[SCOPE_KEY] = project_id


def session_scope(session: AsyncSession | Session) -> uuid.UUID | None:
    target = session.sync_session if isinstance(session, AsyncSession) else session
    return target.info.get(SCOPE_KEY)


@event.listens_for(Session, "do_orm_execute")
def _apply_project_scope(state: ORMExecuteState) -> None:
    project_id = state.session.info.get(SCOPE_KEY)
    if project_id is None:
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if state.is_column_load or state.is_relationship_load:
        return
    if state.execution_options.get(ALL_PROJECTS, False):
        return
    state.statement = state.statement.options(
        *(
            with_loader_criteria(
                model,
                lambda cls: cls.project_id == project_id,
                include_aliases=True,
            )
            for model in SCOPED_MODELS
        )
    )


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


async def site_project(db: AsyncSession) -> Project | None:
    """The current project, or — between End and the next Start — the last one.

    Mirrors ruth_current_project_id() in the database, which tags new rows.
    """
    rows = (
        await db.execute(
            select(Project).order_by(Project.started_at.desc()),
            execution_options={ALL_PROJECTS: True},
        )
    ).scalars().all()
    current = next((p for p in rows if p.state in CURRENT_PROJECT_STATES), None)
    return current or (rows[0] if rows else None)


async def find_project(db: AsyncSession, ref: str) -> Project | None:
    """A project by id or slug."""
    ref = ref.strip()
    try:
        pid = uuid.UUID(ref)
    except ValueError:
        return (await db.execute(select(Project).where(Project.slug == ref))).scalars().first()
    return await db.get(Project, pid)


async def resolve_scope(db: AsyncSession, path: str, ref: str | None) -> ProjectScope:
    """Which project this request reads (see the module docstring)."""
    mode = path_mode(path)
    site = await site_project(db)
    if mode == "by_id":
        return ProjectScope(project=site, is_current=True, filtered=False)
    if mode == "scoped" and ref:
        project = await find_project(db, ref)
        if project is None:
            raise UnknownProjectError(ref)
        return ProjectScope(project=project, is_current=site is not None and project.id == site.id)
    return ProjectScope(project=site, is_current=True)
