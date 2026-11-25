"""Shared fixtures: settings that never read .env, in-memory storage and services per test."""

import os
from uuid import UUID

import pytest

from app.core.config import Settings
from app.repositories.annotation_file import InMemoryAnnotationFileRepository
from app.repositories.project import InMemoryProjectRepository
from app.repositories.vcf_file import InMemoryVcfFileRepository
from app.schemas.project import ProjectCreate
from app.services.annotation_file import AnnotationFileService
from app.services.project import ProjectService
from app.services.vcf_file import VcfFileService
from app.storage.files import InMemoryFileStorage

MAX_BYTES = 1024 * 1024
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://app:app@localhost:5433/gva_test"
)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(_env_file=None, database_url=TEST_DATABASE_URL)  # pyright: ignore[reportCallIssue]


@pytest.fixture
def repository() -> InMemoryProjectRepository:
    return InMemoryProjectRepository()


@pytest.fixture
def storage() -> InMemoryFileStorage:
    return InMemoryFileStorage()


@pytest.fixture
def vcf_repository() -> InMemoryVcfFileRepository:
    return InMemoryVcfFileRepository()


@pytest.fixture
def annotation_repository() -> InMemoryAnnotationFileRepository:
    return InMemoryAnnotationFileRepository()


@pytest.fixture
def service(repository: InMemoryProjectRepository, storage: InMemoryFileStorage) -> ProjectService:
    return ProjectService(repository, storage)


@pytest.fixture
def vcf_service(
    repository: InMemoryProjectRepository,
    vcf_repository: InMemoryVcfFileRepository,
    storage: InMemoryFileStorage,
) -> VcfFileService:
    return VcfFileService(repository, vcf_repository, storage, MAX_BYTES)


@pytest.fixture
def annotation_service(
    repository: InMemoryProjectRepository,
    annotation_repository: InMemoryAnnotationFileRepository,
    storage: InMemoryFileStorage,
) -> AnnotationFileService:
    return AnnotationFileService(repository, annotation_repository, storage, MAX_BYTES)


@pytest.fixture
async def project_id(repository: InMemoryProjectRepository) -> UUID:
    project = await repository.add(ProjectCreate(name="BRCA", lead_scientist="R. Franklin"))
    return project.project_id
