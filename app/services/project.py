"""Business rules for projects (Service Layer); storage is reached only through the repository"""

import logging
from uuid import UUID

from app.core.exceptions import ProjectNameConflictError, ProjectNotFoundError
from app.models import ProjectModel
from app.repositories.project import ProjectRepository
from app.schemas.project import ProjectCreate

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    async def create_project(self, data: ProjectCreate) -> ProjectModel:
        try:
            project = await self._repository.add(data)
        except ProjectNameConflictError:
            logger.warning("Project not created: name already exists")
            raise
        logger.info("Project created project_id=%s", project.project_id)
        return project

    async def list_projects(self) -> list[ProjectModel]:
        return await self._repository.list_all()

    async def delete_project(self, project_id: UUID) -> None:
        project = await self._repository.get(project_id)
        if project is None:
            logger.warning(
                "Project not deleted: project_id=%s not found",
                project_id,
            )
            raise ProjectNotFoundError(project_id)
        await self._repository.delete(project)
        logger.info("Project deleted project_id=%s", project_id)
