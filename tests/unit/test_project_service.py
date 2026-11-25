import logging
from uuid import uuid4

import pytest

from app.core.exceptions import ProjectNameConflictError, ProjectNotFoundError
from app.schemas.project import ProjectCreate
from app.services.project import ProjectService
from app.storage.files import InMemoryFileStorage


def new_project(name: str = "BRCA cohort") -> ProjectCreate:
    return ProjectCreate(name=name, lead_scientist="Rosalind Franklin")


async def test_create_project_logs_id(
    service: ProjectService, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        project = await service.create_project(new_project())

    assert f"Project created project_id={project.project_id}" in caplog.messages


async def test_create_duplicate_raises_and_warns(
    service: ProjectService, caplog: pytest.LogCaptureFixture
) -> None:
    await service.create_project(new_project())

    with pytest.raises(ProjectNameConflictError):
        await service.create_project(new_project())

    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_list_projects_in_creation_order(service: ProjectService) -> None:
    first = await service.create_project(new_project("first"))
    second = await service.create_project(new_project("second"))

    assert await service.list_projects() == [first, second]


async def test_delete_project_removes_it(service: ProjectService) -> None:
    project = await service.create_project(new_project())

    await service.delete_project(project.project_id)

    assert await service.list_projects() == []


async def test_delete_unknown_project_raises_and_warns(
    service: ProjectService, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(ProjectNotFoundError):
        await service.delete_project(uuid4())

    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_delete_project_removes_its_files(
    service: ProjectService, storage: InMemoryFileStorage
) -> None:
    project = await service.create_project(new_project())
    other = await service.create_project(new_project("other"))
    await storage.put(f"projects/{project.project_id}/vcf/a.vcf", b"x")
    await storage.put(f"projects/{other.project_id}/vcf/b.vcf", b"y")

    await service.delete_project(project.project_id)

    assert list(storage.objects) == [f"projects/{other.project_id}/vcf/b.vcf"]
