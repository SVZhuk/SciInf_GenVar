import logging
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

URL = "/api/v1/projects/"


def new_project(name: str = "BRCA cohort") -> dict[str, str]:
    return {"name": name, "lead_scientist": "Rosalind Franklin", "description": "WES, 2026"}


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_create_project_returns_201(client: AsyncClient) -> None:
    response = await client.post(URL, json=new_project())

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "BRCA cohort"
    assert body["lead_scientist"] == "Rosalind Franklin"
    assert body["description"] == "WES, 2026"
    assert body["completed_at"] is None
    assert set(body) == {
        "project_id",
        "name",
        "lead_scientist",
        "description",
        "created_at",
        "completed_at",
    }


async def test_create_duplicate_name_returns_409(client: AsyncClient) -> None:
    await client.post(URL, json=new_project())

    response = await client.post(URL, json=new_project())

    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "BRCA cohort"},
        {"name": "", "lead_scientist": "Rosalind Franklin"},
        {"name": "BRCA cohort", "lead_scientist": "x" * 101},
    ],
)
async def test_create_invalid_payload_returns_422(
    client: AsyncClient, payload: dict[str, Any]
) -> None:
    response = await client.post(URL, json=payload)

    assert response.status_code == 422


async def test_list_projects(client: AsyncClient) -> None:
    first = (await client.post(URL, json=new_project("first"))).json()
    second = (await client.post(URL, json=new_project("second"))).json()

    response = await client.get(URL)

    assert response.status_code == 200
    assert response.json() == [first, second]


async def test_list_projects_empty(client: AsyncClient) -> None:
    response = await client.get(URL)

    assert response.status_code == 200
    assert response.json() == []


async def test_delete_project_return_204(client: AsyncClient) -> None:
    project_id = (await client.post(URL, json=new_project())).json()["project_id"]

    response = await client.delete(f"{URL}{project_id}/")

    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get(URL)).json() == []


async def test_delete_unknown_project_returns_404(client: AsyncClient) -> None:
    response = await client.delete(f"{URL}{uuid4()}/")

    assert response.status_code == 404


async def test_delete_invalid_uuid_returns_422(client: AsyncClient) -> None:
    response = await client.delete(f"{URL}not-a-uuid/")

    assert response.status_code == 422


async def test_request_is_logged_without_query_string(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        await client.get(URL, params={"token": "secret"})

    assert "GET /api/v1/projects/ -> 200" in caplog.text
    assert "secret" not in caplog.text


async def test_client_error_is_logged_as_warning(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    await client.delete(f"{URL}{uuid4()}/")

    assert any(
        record.name == "app.request" and record.levelno == logging.WARNING
        for record in caplog.records
    )
