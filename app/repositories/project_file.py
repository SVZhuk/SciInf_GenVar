"""Data access shared by every file type stored inside a project."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_file import ProjectFileMixin


class ProjectFileRepository[M: ProjectFileMixin](Protocol):
    async def list_for_project(self, project_id: UUID) -> list[M]: ...
    async def get(self, project_id: UUID, file_id: UUID) -> M | None: ...
    async def delete(self, item: M) -> None: ...


class SqlAlchemyProjectFileRepository[M: ProjectFileMixin]:
    model: type[M]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_project(self, project_id: UUID) -> list[M]:
        result = await self._session.scalars(
            select(self.model)
            .where(self.model.project_id == project_id)
            .order_by(self.model.uploaded_at, self.model.file_id)
        )
        return list(result)

    async def get(self, project_id: UUID, file_id: UUID) -> M | None:
        return await self._session.scalar(
            select(self.model).where(
                self.model.file_id == file_id, self.model.project_id == project_id
            )
        )

    async def delete(self, item: M) -> None:
        await self._session.delete(item)
        await self._session.flush()

    async def _insert(self, item: M) -> None:
        self._session.add(item)
        await self._session.flush()


class InMemoryProjectFileRepository[M: ProjectFileMixin]:
    """Files indexed by project then id: lookups and deletes are O(1)."""

    def __init__(self) -> None:
        self._files: dict[UUID, dict[UUID, M]] = {}

    async def list_for_project(self, project_id: UUID) -> list[M]:
        return list(self._files.get(project_id, {}).values())

    async def get(self, project_id: UUID, file_id: UUID) -> M | None:
        return self._files.get(project_id, {}).get(file_id)

    async def delete(self, item: M) -> None:
        del self._files[item.project_id][item.file_id]

    def _insert(self, item: M) -> None:
        item.uploaded_at = datetime.now(UTC)
        self._files.setdefault(item.project_id, {})[item.file_id] = item
