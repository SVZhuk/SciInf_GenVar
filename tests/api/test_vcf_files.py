import gzip
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.api.deps import get_vcf_file_service
from app.api.uploads import MULTIPART_OVERHEAD_BYTES
from app.core.config import Settings
from app.main import create_app
from app.services.vcf_file import VcfFileService
from tests.api.helpers import PROJECTS, create_project, upload
from tests.samples import sample_vcf


def vcf_url(project_id: str) -> str:
    return f"{PROJECTS}{project_id}/vcf/"


async def test_upload_returns_201_with_metadata(client: AsyncClient) -> None:
    project_id = await create_project(client)

    body = await upload(client, vcf_url(project_id), "calls.vcf", sample_vcf())

    assert body["project_id"] == project_id
    assert (body["filename"], body["variant_count"], body["sample_count"]) == ("calls.vcf", 3, 0)
    assert set(body) == {
        "vcf_file_id",
        "project_id",
        "filename",
        "sample_count",
        "variant_count",
        "uploaded_at",
    }


async def test_upload_sets_location_of_new_file(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(vcf_url(project_id), files={"file": ("a.vcf", sample_vcf())})

    location = response.headers["location"]
    assert location.endswith(f"{vcf_url(project_id)}{response.json()['vcf_file_id']}")
    assert (await client.get(location)).status_code == 200


async def test_upload_gzip_returns_201(client: AsyncClient) -> None:
    project_id = await create_project(client)

    body = await upload(client, vcf_url(project_id), "calls.vcf.gz", gzip.compress(sample_vcf()))

    assert body["variant_count"] == 3


async def test_upload_unknown_project_returns_404(client: AsyncClient) -> None:
    response = await client.post(vcf_url(str(uuid4())), files={"file": ("a.vcf", sample_vcf())})

    assert response.status_code == 404


async def test_upload_bad_extension_returns_422(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(vcf_url(project_id), files={"file": ("a.txt", sample_vcf())})

    assert response.status_code == 422


async def test_upload_invalid_vcf_returns_422_with_line(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(vcf_url(project_id), files={"file": ("a.vcf", b"garbage")})

    assert response.status_code == 422
    assert "line 1" in response.json()["detail"]


async def test_upload_without_file_returns_422(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(vcf_url(project_id))

    assert response.status_code == 422


async def test_upload_too_large_returns_413(
    settings: Settings, vcf_service: VcfFileService
) -> None:
    app = create_app(settings.model_copy(update={"max_upload_bytes": 10}))
    app.dependency_overrides[get_vcf_file_service] = lambda: vcf_service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(vcf_url(str(uuid4())), files={"file": ("a.vcf", b"x" * 11)})

    assert response.status_code == 413


async def test_list_returns_uploaded_files(client: AsyncClient) -> None:
    project_id = await create_project(client)
    first = await upload(client, vcf_url(project_id), "a.vcf", sample_vcf())
    second = await upload(client, vcf_url(project_id), "b.vcf", sample_vcf())

    response = await client.get(vcf_url(project_id))

    assert response.status_code == 200
    assert response.json() == [first, second]


async def test_list_unknown_project_returns_404(client: AsyncClient) -> None:
    response = await client.get(vcf_url(str(uuid4())))

    assert response.status_code == 404


async def test_get_returns_metadata_and_variants(client: AsyncClient) -> None:
    project_id = await create_project(client)
    vcf_file = await upload(client, vcf_url(project_id), "calls.vcf", sample_vcf())

    response = await client.get(f"{vcf_url(project_id)}{vcf_file['vcf_file_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["vcf_file_id"] == vcf_file["vcf_file_id"]
    assert [(v["chrom"], v["pos"], v["alt"], v["af"]) for v in body["variants"]] == [
        ("chr1", 100, "G", 0.25),
        ("chr2", 200, "T", 0.1),
        ("chr2", 200, "A", 0.2),
    ]


async def test_get_pages_variants(client: AsyncClient) -> None:
    project_id = await create_project(client)
    vcf_file = await upload(client, vcf_url(project_id), "calls.vcf", sample_vcf())
    url = f"{vcf_url(project_id)}{vcf_file['vcf_file_id']}"

    response = await client.get(url, params={"limit": 1, "offset": 2})

    assert [v["alt"] for v in response.json()["variants"]] == ["A"]


async def test_get_invalid_limit_returns_422(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.get(f"{vcf_url(project_id)}{uuid4()}", params={"limit": 0})

    assert response.status_code == 422


async def test_get_unknown_file_returns_404(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.get(f"{vcf_url(project_id)}{uuid4()}")

    assert response.status_code == 404


async def test_delete_returns_204(client: AsyncClient) -> None:
    project_id = await create_project(client)
    vcf_file = await upload(client, vcf_url(project_id), "calls.vcf", sample_vcf())

    response = await client.delete(f"{vcf_url(project_id)}{vcf_file['vcf_file_id']}")

    assert response.status_code == 204
    assert (await client.get(vcf_url(project_id))).json() == []


async def test_delete_unknown_file_returns_404(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.delete(f"{vcf_url(project_id)}{uuid4()}")

    assert response.status_code == 404


async def test_delete_in_unknown_project_returns_404(client: AsyncClient) -> None:
    response = await client.delete(f"{vcf_url(str(uuid4()))}{uuid4()}")

    assert response.status_code == 404


async def test_announced_oversized_body_is_rejected_before_parsing(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"max_upload_bytes": 10}))
    body = b"x" * (MULTIPART_OVERHEAD_BYTES + 11)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(vcf_url(str(uuid4())), files={"file": ("a.vcf", body)})

    assert response.status_code == 413
