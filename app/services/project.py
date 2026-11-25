"""Business rules for projects (Service Layer); storage is reached only through the repository"""

import logging
from uuid import UUID

from app.core.exceptions import ProjectNameConflictError
from app.models import ProjectModel
from app.repositories.project import ProjectRepository
from app.schemas.project import ProjectCreate
from app.services.project_files import require_project
from app.storage.files import FileStorage, project_prefix

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, repository: ProjectRepository, storage: FileStorage) -> None:
        self._repository = repository
        self._storage = storage

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
        """Rows cascade in the database; the files under the project prefix are removed here."""
        project = await require_project(self._repository, project_id)
        await self._repository.delete(project)
        await self._storage.delete_prefix(project_prefix(project_id))
        logger.info("Project deleted project_id=%s", project_id)
