"""Shared fixtures: settings that never read .env, and an in-memory service per test."""

import os

import pytest

from app.core.config import Settings
from app.repositories.project import InMemoryProjectRepository
from app.services.project import ProjectService

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
def service(repository: InMemoryProjectRepository) -> ProjectService:
    return ProjectService(repository)
