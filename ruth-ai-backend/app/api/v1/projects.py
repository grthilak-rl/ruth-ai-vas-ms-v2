"""Read-only project list for the portal's project view mode.

- GET /api/v1/projects                  every project, newest first, and which is current
- GET /api/v1/projects/{ref}/cameras    the cameras of a project (id or slug)

Open to every portal user, like the Violations page: the banner ("Viewing
HPCL, ended 17 Nov") and links into a past project need the name and dates.
Audit fields, counts and every action stay on /admin/projects.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, union

from app.core.project_scope import ALL_PROJECTS, find_project
from app.deps import DBSession
from app.models import Device, ProjectCamera, StreamSession, Violation
from app.models.project import CURRENT_PROJECT_STATES
from app.schemas.project import ProjectBrief, ProjectBriefList, ProjectCameraInfo

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("", response_model=ProjectBriefList, summary="List projects")
async def list_projects(db: DBSession) -> ProjectBriefList:
    from app.services.project_service import ProjectService

    projects = await ProjectService(db).list_projects()
    items = []
    for p in projects:
        brief = ProjectBrief.model_validate(p)
        # Only a project that is actually current (active/stopping/stopped/
        # resuming). Between End and the next Start there is none, and the
        # ended project must not be labelled "Current" next to "Ended".
        brief.is_current = p.state in CURRENT_PROJECT_STATES
        items.append(brief)
    return ProjectBriefList(items=items, current=next((i for i in items if i.is_current), None))


@router.get(
    "/{ref}/cameras",
    response_model=list[ProjectCameraInfo],
    summary="Cameras of a project",
    description=(
        "The cameras picked when the project started, plus every camera its "
        "data came from. Includes cameras disabled since, so a past "
        "project's camera filter still lists them."
    ),
)
async def project_cameras(ref: str, db: DBSession) -> list[ProjectCameraInfo]:
    project = await find_project(db, ref)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "project_not_found", "message": f"No project {ref!r}"},
        )
    ids = union(
        select(ProjectCamera.device_id).where(ProjectCamera.project_id == project.id),
        select(Violation.device_id).where(Violation.project_id == project.id).distinct(),
        select(StreamSession.device_id).where(StreamSession.project_id == project.id).distinct(),
    ).subquery()
    devices = (
        await db.execute(
            select(Device).where(Device.id.in_(select(ids.c[0]))).order_by(Device.name),
            execution_options={ALL_PROJECTS: True},
        )
    ).scalars().all()
    return [
        ProjectCameraInfo(id=d.id, name=d.name, display_name=d.display_name, enabled=d.enabled)
        for d in devices
    ]
