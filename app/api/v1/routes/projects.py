from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ProjectServiceDep
from app.core.exceptions import ProjectNameConflictError, ProjectNotFoundError
from app.schemas.project import ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, service: ProjectServiceDep) -> ProjectRead:
    try:
        project = await service.create_project(payload)
    except ProjectNameConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    return ProjectRead.model_validate(project)


@router.get("/", response_model=list[ProjectRead])
async def list_projects(service: ProjectServiceDep) -> list[ProjectRead]:
    return [ProjectRead.model_validate(project) for project in await service.list_projects()]


@router.delete("/{project_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: UUID, service: ProjectServiceDep) -> None:
    try:
        await service.delete_project(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
