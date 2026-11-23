"""Data access for projects (Repository pattern): only this touches storage."""

import logging
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProjectNameConflictError
from app.models import ProjectModel
from app.schemas.project import ProjectCreate

logger = logging.getLogger(__name__)

UNIQUE_NAME_CONSTRAINT = "uq_projects_name"
UNIQUE_VIOLATION_SQLSTATE = "23505"


def _is_name_conflict(exc: IntegrityError) -> bool:
    cause = getattr(exc.orig, "__cause__", None)  # original asyncpg exception
    return (
        getattr(exc.orig, "sqlstate", None) == UNIQUE_VIOLATION_SQLSTATE
        and getattr(cause, "constraint_name", None) == UNIQUE_NAME_CONSTRAINT
    )


class ProjectRepository(Protocol):
    async def add(self, data: ProjectCreate) -> ProjectModel: ...
    async def list_all(self) -> list[ProjectModel]: ...
    async def get(self, project_id: UUID) -> ProjectModel | None: ...
    async def delete(self, project: ProjectModel) -> None: ...


class SqlAlchemyProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: ProjectCreate) -> ProjectModel:
        project = ProjectModel(**data.model_dump())
        self._session.add(project)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if _is_name_conflict(exc):
                raise ProjectNameConflictError(data.name) from exc
            raise
        logger.debug("Inserted project row project_id=%s", project.project_id)
        return project

    async def list_all(self) -> list[ProjectModel]:
        result = await self._session.scalars(
            select(ProjectModel).order_by(ProjectModel.created_at, ProjectModel.project_id)
        )
        projects = list(result)
        logger.debug("Fetched %d project rows", len(projects))
        return projects

    async def get(self, project_id: UUID) -> ProjectModel | None:
        return await self._session.get(ProjectModel, project_id)

    async def delete(self, project: ProjectModel) -> None:
        await self._session.delete(project)
        await self._session.flush()
        logger.debug("Deleted project row project_id=%s", project.project_id)


class InMemoryProjectRepository:
    """Dict-based storage for fast tests: O(1) lookup by id and O(1) duplicate name check."""

    def __init__(self) -> None:
        self._projects: dict[UUID, ProjectModel] = {}
        self._names: set[str] = set()

    async def add(self, data: ProjectCreate) -> ProjectModel:
        if data.name in self._names:
            raise ProjectNameConflictError(data.name)
        project = ProjectModel(
            project_id=uuid4(), created_at=datetime.now(UTC), **data.model_dump()
        )
        self._projects[project.project_id] = project
        self._names.add(project.name)
        return project

    async def list_all(self) -> list[ProjectModel]:
        return list(self._projects.values())

    async def get(self, project_id: UUID) -> ProjectModel | None:
        return self._projects.get(project_id)

    async def delete(self, project: ProjectModel) -> None:
        del self._projects[project.project_id]
        self._names.discard(project.name)
