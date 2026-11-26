"""Full stack against Postgres: upload, read and delete files, then delete the project."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.storage.files import InMemoryFileStorage
from tests.samples import sample_clinvar, sample_vcf

pytestmark = pytest.mark.integration

PROJECTS = "/api/v1/projects/"


async def test_file_lifecycle(e2e_client: AsyncClient, storage: InMemoryFileStorage) -> None:
    payload = {"name": f"e2e-{uuid4()}", "lead_scientist": "Rosalind Franklin"}
    project_id = (await e2e_client.post(PROJECTS, json=payload)).json()["project_id"]
    base = f"{PROJECTS}{project_id}"

    vcf = await e2e_client.post(f"{base}/vcf/", files={"file": ("calls.vcf", sample_vcf())})
    annotation = await e2e_client.post(
        f"{base}/annotation/", files={"file": ("clinvar.txt", sample_clinvar())}
    )
    assert (vcf.status_code, annotation.status_code) == (201, 201)
    detail = await e2e_client.get(f"{base}/vcf/{vcf.json()['vcf_file_id']}")
    assert len(detail.json()["variants"]) == 3
    assert len(storage.objects) == 2

    deleted = await e2e_client.delete(f"{base}/")

    assert deleted.status_code == 204
    assert storage.objects == {}
    assert (await e2e_client.get(f"{base}/vcf/")).status_code == 404
