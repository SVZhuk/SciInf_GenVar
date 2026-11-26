"""ClinVar annotation file use cases: validate, count entries, store, list, delete."""

import logging
from uuid import UUID, uuid4

from app.core.exceptions import AnnotationFileNotFoundError
from app.models import AnnotationFileModel
from app.parsers.clinvar import parse_clinvar
from app.repositories.annotation_file import AnnotationFileRepository
from app.repositories.project import ProjectRepository
from app.services.project_files import parse_upload, require_file, require_project
from app.storage.files import FileStorage, object_key

logger = logging.getLogger(__name__)

ANNOTATION_EXTENSIONS = (".txt.gz", ".tsv.gz", ".txt", ".tsv")


class AnnotationFileService:
    def __init__(
        self,
        projects: ProjectRepository,
        annotation_files: AnnotationFileRepository,
        storage: FileStorage,
        max_bytes: int,
    ) -> None:
        self._projects = projects
        self._annotation_files = annotation_files
        self._storage = storage
        self._max_bytes = max_bytes

    async def upload(self, project_id: UUID, filename: str, data: bytes) -> AnnotationFileModel:
        """Same order and consistency rules as VcfFileService.upload."""
        await require_project(self._projects, project_id)
        extension, summary = await parse_upload(
            project_id, filename, data, ANNOTATION_EXTENSIONS, parse_clinvar, self._max_bytes
        )
        if summary.invalid_count:
            logger.warning(
                "Annotation file has %d invalid entries project_id=%s",
                summary.invalid_count,
                project_id,
            )
        annotation_file_id = uuid4()
        annotation_file = AnnotationFileModel(
            annotation_file_id=annotation_file_id,
            project_id=project_id,
            filename=filename,
            s3_key=object_key(project_id, "annotation", annotation_file_id, extension),
            column_format=summary.column_format,
            entry_count=summary.entry_count,
        )
        await self._annotation_files.add(annotation_file)
        await self._storage.put(annotation_file.s3_key, data)
        logger.info(
            "Annotation file uploaded annotation_file_id=%s project_id=%s format=%s entries=%d",
            annotation_file_id,
            project_id,
            summary.column_format,
            summary.entry_count,
        )
        return annotation_file

    async def list_annotation_files(self, project_id: UUID) -> list[AnnotationFileModel]:
        await require_project(self._projects, project_id)
        return await self._annotation_files.list_for_project(project_id)

    async def delete_annotation_file(self, project_id: UUID, annotation_file_id: UUID) -> None:
        annotation_file = await require_file(
            self._projects,
            self._annotation_files,
            project_id,
            annotation_file_id,
            AnnotationFileNotFoundError,
        )
        await self._annotation_files.delete(annotation_file)
        await self._storage.delete(annotation_file.s3_key)
        logger.info(
            "Annotation file deleted annotation_file_id=%s project_id=%s",
            annotation_file_id,
            project_id,
        )
