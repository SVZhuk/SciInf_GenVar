"""Dependency Injection wiring: the place that picks concrete implementations."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.repositories.project import SqlAlchemyProjectRepository
from app.services.project import ProjectService

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


def get_project_service(session: SessionDep) -> ProjectService:
    return ProjectService(SqlAlchemyProjectRepository(session))


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
