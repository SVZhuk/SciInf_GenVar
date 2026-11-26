"""Data access for annotation files (Repository pattern)."""

from typing import Protocol

from app.models import AnnotationFileModel
from app.repositories.project_file import (
    InMemoryProjectFileRepository,
    ProjectFileRepository,
    SqlAlchemyProjectFileRepository,
)


class AnnotationFileRepository(ProjectFileRepository[AnnotationFileModel], Protocol):
    async def add(self, annotation_file: AnnotationFileModel) -> AnnotationFileModel: ...


class SqlAlchemyAnnotationFileRepository(SqlAlchemyProjectFileRepository[AnnotationFileModel]):
    model = AnnotationFileModel

    async def add(self, annotation_file: AnnotationFileModel) -> AnnotationFileModel:
        await self._insert(annotation_file)
        return annotation_file


class InMemoryAnnotationFileRepository(InMemoryProjectFileRepository[AnnotationFileModel]):
    async def add(self, annotation_file: AnnotationFileModel) -> AnnotationFileModel:
        self._insert(annotation_file)
        return annotation_file
