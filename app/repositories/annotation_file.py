"""Data access for annotation files (Repository pattern)."""

import logging
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnnotationFileModel

logger = logging.getLogger(__name__)


class AnnotationFileRepository(Protocol):
    async def add(self, annotation_file: AnnotationFileModel) -> AnnotationFileModel: ...
    async def list_for_project(self, project_id: UUID) -> list[AnnotationFileModel]: ...
    async def get(
        self, project_id: UUID, annotation_file_id: UUID
    ) -> AnnotationFileModel | None: ...
    async def delete(self, annotation_file: AnnotationFileModel) -> None: ...


class SqlAlchemyAnnotationFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, annotation_file: AnnotationFileModel) -> AnnotationFileModel:
        self._session.add(annotation_file)
        await self._session.flush()
        logger.debug(
            "Inserted annotation_file row annotation_file_id=%s",
            annotation_file.annotation_file_id,
        )
        return annotation_file

    async def list_for_project(self, project_id: UUID) -> list[AnnotationFileModel]:
        result = await self._session.scalars(
            select(AnnotationFileModel)
            .where(AnnotationFileModel.project_id == project_id)
            .order_by(AnnotationFileModel.uploaded_at, AnnotationFileModel.annotation_file_id)
        )
        return list(result)

    async def get(self, project_id: UUID, annotation_file_id: UUID) -> AnnotationFileModel | None:
        return await self._session.scalar(
            select(AnnotationFileModel).where(
                AnnotationFileModel.annotation_file_id == annotation_file_id,
                AnnotationFileModel.project_id == project_id,
            )
        )

    async def delete(self, annotation_file: AnnotationFileModel) -> None:
        await self._session.delete(annotation_file)
        await self._session.flush()
        logger.debug(
            "Deleted annotation_file row annotation_file_id=%s",
            annotation_file.annotation_file_id,
        )


class InMemoryAnnotationFileRepository:
    """Files indexed by project then id: lookups and deletes are O(1)."""

    def __init__(self) -> None:
        self._files: dict[UUID, dict[UUID, AnnotationFileModel]] = {}

    async def add(self, annotation_file: AnnotationFileModel) -> AnnotationFileModel:
        annotation_file.uploaded_at = datetime.now(UTC)
        files = self._files.setdefault(annotation_file.project_id, {})
        files[annotation_file.annotation_file_id] = annotation_file
        return annotation_file

    async def list_for_project(self, project_id: UUID) -> list[AnnotationFileModel]:
        return list(self._files.get(project_id, {}).values())

    async def get(self, project_id: UUID, annotation_file_id: UUID) -> AnnotationFileModel | None:
        return self._files.get(project_id, {}).get(annotation_file_id)

    async def delete(self, annotation_file: AnnotationFileModel) -> None:
        del self._files[annotation_file.project_id][annotation_file.annotation_file_id]
