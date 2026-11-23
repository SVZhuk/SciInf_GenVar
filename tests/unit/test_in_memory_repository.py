from uuid import uuid4

import pytest

from app.core.exceptions import ProjectNameConflictError
from app.repositories.project import InMemoryProjectRepository
from app.schemas.project import ProjectCreate


def new_project(name: str = "BRCA cohort") -> ProjectCreate:
    return ProjectCreate(name=name, lead_scientist="Rosalind Franklin")


async def test_add_sets_server_owned_field(repository: InMemoryProjectRepository) -> None:
    project = await repository.add(new_project())

    assert project.project_id is not None
    assert project.created_at.tzinfo is not None
    assert project.completed_at is None


async def test_add_generates_unique_project_ids(repository: InMemoryProjectRepository) -> None:
    first = await repository.add(new_project("first"))
    second = await repository.add(new_project("second"))

    assert first.project_id != second.project_id


async def test_add_reject_duplicate_name(repository: InMemoryProjectRepository) -> None:
    await repository.add(new_project())

    with pytest.raises(ProjectNameConflictError):
        await repository.add(new_project())


async def test_get_unknown_id_returns_none(repository: InMemoryProjectRepository) -> None:
    assert await repository.get(uuid4()) is None


async def test_delete_frees_the_name(repository: InMemoryProjectRepository) -> None:
    project = await repository.add(new_project())

    await repository.delete(project)

    assert await repository.get(project.project_id) is None
    assert (await repository.add(new_project())).name == "BRCA cohort"
