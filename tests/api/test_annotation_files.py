from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.api.deps import get_annotation_file_service
from app.core.config import Settings
from app.main import create_app
from app.services.annotation_file import AnnotationFileService
from tests.api.helpers import PROJECTS, create_project, upload
from tests.samples import sample_clinvar


def annotation_url(project_id: str) -> str:
    return f"{PROJECTS}{project_id}/annotation/"


async def test_upload_returns_201_with_metadata(client: AsyncClient) -> None:
    project_id = await create_project(client)

    body = await upload(client, annotation_url(project_id), "clinvar.txt", sample_clinvar())

    assert (body["column_format"], body["entry_count"]) == ("simplified", 1)
    assert set(body) == {
        "annotation_file_id",
        "project_id",
        "filename",
        "column_format",
        "entry_count",
        "uploaded_at",
    }


async def test_upload_unknown_project_returns_404(client: AsyncClient) -> None:
    files = {"file": ("clinvar.txt", sample_clinvar())}

    response = await client.post(annotation_url(str(uuid4())), files=files)

    assert response.status_code == 404


async def test_upload_bad_extension_returns_422(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(
        annotation_url(project_id), files={"file": ("clinvar.csv", sample_clinvar())}
    )

    assert response.status_code == 422


async def test_upload_invalid_format_returns_422(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(
        annotation_url(project_id), files={"file": ("clinvar.txt", b"a\tb\n1\t2\n")}
    )

    assert response.status_code == 422


async def test_list_returns_uploaded_files(client: AsyncClient) -> None:
    project_id = await create_project(client)
    uploaded = await upload(client, annotation_url(project_id), "clinvar.txt", sample_clinvar())

    response = await client.get(annotation_url(project_id))

    assert response.status_code == 200
    assert response.json() == [uploaded]


async def test_list_unknown_project_returns_404(client: AsyncClient) -> None:
    response = await client.get(annotation_url(str(uuid4())))

    assert response.status_code == 404


async def test_delete_returns_204(client: AsyncClient) -> None:
    project_id = await create_project(client)
    uploaded = await upload(client, annotation_url(project_id), "clinvar.txt", sample_clinvar())

    response = await client.delete(f"{annotation_url(project_id)}{uploaded['annotation_file_id']}")

    assert response.status_code == 204
    assert (await client.get(annotation_url(project_id))).json() == []


async def test_delete_unknown_file_returns_404(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.delete(f"{annotation_url(project_id)}{uuid4()}")

    assert response.status_code == 404


async def test_upload_without_file_returns_422(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(annotation_url(project_id))

    assert response.status_code == 422


async def test_upload_too_large_returns_413(
    settings: Settings, annotation_service: AnnotationFileService
) -> None:
    app = create_app(settings.model_copy(update={"max_upload_bytes": 10}))
    app.dependency_overrides[get_annotation_file_service] = lambda: annotation_service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            annotation_url(str(uuid4())), files={"file": ("clinvar.txt", b"x" * 11)}
        )

    assert response.status_code == 413


async def test_delete_in_unknown_project_returns_404(client: AsyncClient) -> None:
    response = await client.delete(f"{annotation_url(str(uuid4()))}{uuid4()}")

    assert response.status_code == 404
