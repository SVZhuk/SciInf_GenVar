"""Dependency Injection wiring: the only place that picks concrete implementations."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_session
from app.db.unit_of_work import AfterCommit, get_after_commit
from app.repositories.annotation_file import SqlAlchemyAnnotationFileRepository
from app.repositories.project import SqlAlchemyProjectRepository
from app.repositories.vcf_file import SqlAlchemyVcfFileRepository
from app.services.annotation_file import AnnotationFileService
from app.services.project import ProjectService
from app.services.vcf_file import VcfFileService
from app.storage.files import DeleteAfterCommitStorage, FileStorage

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


def get_file_storage(
    request: Request, after_commit: Annotated[AfterCommit, Depends(get_after_commit)]
) -> FileStorage:
    storage: FileStorage = request.app.state.file_storage
    return DeleteAfterCommitStorage(storage, after_commit)


FileStorageDep = Annotated[FileStorage, Depends(get_file_storage)]


def get_max_upload_bytes(request: Request) -> int:
    settings: Settings = request.app.state.settings
    return settings.max_upload_bytes


MaxUploadBytesDep = Annotated[int, Depends(get_max_upload_bytes)]


def get_project_service(session: SessionDep, storage: FileStorageDep) -> ProjectService:
    return ProjectService(SqlAlchemyProjectRepository(session), storage)


def get_vcf_file_service(
    session: SessionDep, storage: FileStorageDep, max_bytes: MaxUploadBytesDep
) -> VcfFileService:
    return VcfFileService(
        SqlAlchemyProjectRepository(session),
        SqlAlchemyVcfFileRepository(session),
        storage,
        max_bytes,
    )


def get_annotation_file_service(
    session: SessionDep, storage: FileStorageDep, max_bytes: MaxUploadBytesDep
) -> AnnotationFileService:
    return AnnotationFileService(
        SqlAlchemyProjectRepository(session),
        SqlAlchemyAnnotationFileRepository(session),
        storage,
        max_bytes,
    )


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
VcfFileServiceDep = Annotated[VcfFileService, Depends(get_vcf_file_service)]
AnnotationFileServiceDep = Annotated[AnnotationFileService, Depends(get_annotation_file_service)]
