from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_project_service
from app.core.config import Settings
from app.main import create_app
from app.services.project import ProjectService


@pytest_asyncio.fixture
async def client(settings: Settings, service: ProjectService) -> AsyncIterator[AsyncClient]:
    """Http client over the real app, with storage swapped for in-memory repository."""
    app = create_app(settings)
    app.dependency_overrides[get_project_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
