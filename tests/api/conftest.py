from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_annotation_file_service, get_project_service, get_vcf_file_service
from app.core.config import Settings
from app.main import create_app
from app.services.annotation_file import AnnotationFileService
from app.services.project import ProjectService
from app.services.vcf_file import VcfFileService


@pytest_asyncio.fixture
async def client(
    settings: Settings,
    service: ProjectService,
    vcf_service: VcfFileService,
    annotation_service: AnnotationFileService,
) -> AsyncIterator[AsyncClient]:
    """HTTP client over the real app, with storage swapped for the in-memory implementations."""
    app = create_app(settings)
    app.dependency_overrides[get_project_service] = lambda: service
    app.dependency_overrides[get_vcf_file_service] = lambda: vcf_service
    app.dependency_overrides[get_annotation_file_service] = lambda: annotation_service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
