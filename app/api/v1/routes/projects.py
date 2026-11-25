from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import ProjectServiceDep
from app.schemas.project import ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, service: ProjectServiceDep) -> ProjectRead:
    return ProjectRead.model_validate(await service.create_project(payload))


@router.get("/")
async def list_projects(service: ProjectServiceDep) -> list[ProjectRead]:
    return [ProjectRead.model_validate(project) for project in await service.list_projects()]


@router.delete("/{project_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: UUID, service: ProjectServiceDep) -> None:
    await service.delete_project(project_id)
