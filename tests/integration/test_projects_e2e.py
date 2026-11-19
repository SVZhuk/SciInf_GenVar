"""Full stack against Postgres: lifespan, per-request session, commit, real SQL."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration

URL = "/api/v1/projects/"


@pytest.mark.usefixtures("engine")
async def test_project_lifecycle(settings: Settings) -> None:
    app = create_app(settings)
    transport = ASGITransport(app=app)
    payload = {"name": f"e2e-{uuid4()}", "lead_scientist": "Rosalind Franklin"}
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        created = await client.post(URL, json=payload)
        assert created.status_code == 201
        assert (await client.post(URL, json=payload)).status_code == 409
        project = created.json()
        assert project in (await client.get(URL)).json()

        deleted = await client.delete(f"{URL}{project['project_id']}/")

        assert deleted.status_code == 204
        assert project not in (await client.get(URL)).json()
