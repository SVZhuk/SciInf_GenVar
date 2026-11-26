"""Full stack against Postgres: lifespan, per-request session, commit, real SQL."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

URL = "/api/v1/projects/"


async def test_project_lifecycle(e2e_client: AsyncClient) -> None:
    payload = {"name": f"e2e-{uuid4()}", "lead_scientist": "Rosalind Franklin"}

    created = await e2e_client.post(URL, json=payload)
    assert created.status_code == 201
    assert (await e2e_client.post(URL, json=payload)).status_code == 409
    project = created.json()
    assert project in (await e2e_client.get(URL)).json()

    deleted = await e2e_client.delete(f"{URL}{project['project_id']}/")

    assert deleted.status_code == 204
    assert project not in (await e2e_client.get(URL)).json()
