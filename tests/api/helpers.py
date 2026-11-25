from typing import Any

from httpx import AsyncClient

PROJECTS = "/api/v1/projects/"


async def create_project(client: AsyncClient) -> str:
    response = await client.post(PROJECTS, json={"name": "BRCA", "lead_scientist": "R. Franklin"})
    project_id: str = response.json()["project_id"]
    return project_id


async def upload(client: AsyncClient, url: str, filename: str, data: bytes) -> dict[str, Any]:
    response = await client.post(url, files={"file": (filename, data)})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body
