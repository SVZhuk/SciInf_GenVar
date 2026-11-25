"""Steps shared by every service that works with files inside a project."""

import asyncio
import logging
from collections.abc import Callable
from uuid import UUID

from app.core.exceptions import (
    InvalidFileFormatError,
    InvalidFilenameError,
    NotFoundError,
    ProjectNotFoundError,
)
from app.models import ProjectModel
from app.models.project_file import ProjectFileMixin
from app.parsers.text import decode_lines, file_extension
from app.repositories.project import ProjectRepository
from app.repositories.project_file import ProjectFileRepository

logger = logging.getLogger(__name__)


async def require_project(projects: ProjectRepository, project_id: UUID) -> ProjectModel:
    project = await projects.get(project_id)
    if project is None:
        logger.warning("Project not found project_id=%s", project_id)
        raise ProjectNotFoundError(project_id)
    return project


async def require_file[M: ProjectFileMixin](
    projects: ProjectRepository,
    files: ProjectFileRepository[M],
    project_id: UUID,
    file_id: UUID,
    not_found: type[NotFoundError],
) -> M:
    await require_project(projects, project_id)
    item = await files.get(project_id, file_id)
    if item is None:
        logger.warning("%s not found file_id=%s project_id=%s", not_found.kind, file_id, project_id)
        raise not_found(file_id)
    return item


async def parse_upload[T](
    project_id: UUID,
    filename: str,
    data: bytes,
    extensions: tuple[str, ...],
    parse: Callable[[list[str]], T],
    max_bytes: int,
) -> tuple[str, T]:
    """Return the matched extension and the parsed content, or raise an invalid input error."""
    try:
        extension = file_extension(filename, extensions)
        parsed = await asyncio.to_thread(_decode_and_parse, data, extension, parse, max_bytes)
    except InvalidFilenameError:
        logger.warning("Upload rejected: bad filename project_id=%s", project_id)
        raise
    except InvalidFileFormatError as exc:
        logger.warning(
            "Upload rejected: project_id=%s line=%s reason=%s", project_id, exc.line_no, exc.reason
        )
        raise
    return extension, parsed


def _decode_and_parse[T](
    data: bytes, extension: str, parse: Callable[[list[str]], T], max_bytes: int
) -> T:
    """CPU-bound, so it runs in a worker thread and the event loop keeps serving requests."""
    return parse(decode_lines(data, extension.endswith(".gz"), max_bytes))
