from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProjectNameConflictError
from app.repositories.project import SqlAlchemyProjectRepository
from app.schemas.project import ProjectCreate

pytestmark = pytest.mark.integration


def new_project(name: str = "BRCA cohort") -> ProjectCreate:
    return ProjectCreate(name=name, lead_scientist="Rosalind Franklin")


@pytest.fixture
def repository(session: AsyncSession) -> SqlAlchemyProjectRepository:
    return SqlAlchemyProjectRepository(session)


async def test_add_sets_server_defaults(repository: SqlAlchemyProjectRepository) -> None:
    project = await repository.add(new_project())

    assert project.project_id is not None
    assert project.created_at is not None
    assert project.completed_at is None


async def test_unique_constraint_maps_to_domain_error(
    repository: SqlAlchemyProjectRepository,
) -> None:
    await repository.add(new_project())

    with pytest.raises(ProjectNameConflictError):
        await repository.add(new_project())


async def test_list_all_returns_added_projects(repository: SqlAlchemyProjectRepository) -> None:
    first = await repository.add(new_project("first"))
    second = await repository.add(new_project("second"))

    assert {project.project_id for project in await repository.list_all()} == {
        first.project_id,
        second.project_id,
    }


async def test_get_and_delete(repository: SqlAlchemyProjectRepository) -> None:
    project = await repository.add(new_project())
    assert await repository.get(project.project_id) is project

    await repository.delete(project)

    assert await repository.get(project.project_id) is None


async def test_get_unknown_id_returns_none(repository: SqlAlchemyProjectRepository) -> None:
    assert await repository.get(uuid4()) is None
