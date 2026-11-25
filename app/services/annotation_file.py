"""ClinVar annotation file use cases: validate, count entries, store, list, delete."""

import asyncio
import logging
from uuid import UUID, uuid4

from app.core.exceptions import (
    AnnotationFileNotFoundError,
    InvalidFileFormatError,
    InvalidFilenameError,
)
from app.models import AnnotationFileModel
from app.parsers.clinvar import ClinVarSummary, parse_clinvar
from app.parsers.text import decode_lines, file_extension
from app.repositories.annotation_file import AnnotationFileRepository
from app.repositories.project import ProjectRepository
from app.services.project import require_project
from app.storage.files import FileStorage, object_key

logger = logging.getLogger(__name__)

ANNOTATION_EXTENSIONS = (".txt.gz", ".tsv.gz", ".txt", ".tsv")


def _parse(data: bytes, extension: str, max_bytes: int) -> ClinVarSummary:
    """CPU-bound, so it runs in a worker thread and the event loop keeps serving requests."""
    return parse_clinvar(decode_lines(data, extension.endswith(".gz"), max_bytes))


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
        try:
            extension = file_extension(filename, ANNOTATION_EXTENSIONS)
            summary = await asyncio.to_thread(_parse, data, extension, self._max_bytes)
        except InvalidFilenameError:
            logger.warning("Annotation upload rejected: bad filename project_id=%s", project_id)
            raise
        except InvalidFileFormatError as exc:
            logger.warning(
                "Annotation upload rejected: project_id=%s line=%s reason=%s",
                project_id,
                exc.line_no,
                exc.reason,
            )
            raise
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
        await require_project(self._projects, project_id)
        annotation_file = await self._annotation_files.get(project_id, annotation_file_id)
        if annotation_file is None:
            logger.warning(
                "Annotation file not found annotation_file_id=%s project_id=%s",
                annotation_file_id,
                project_id,
            )
            raise AnnotationFileNotFoundError(annotation_file_id)
        await self._annotation_files.delete(annotation_file)
        await self._storage.delete(annotation_file.s3_key)
        logger.info(
            "Annotation file deleted annotation_file_id=%s project_id=%s",
            annotation_file_id,
            project_id,
        )
