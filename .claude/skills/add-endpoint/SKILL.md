---
name: add-endpoint
description: Add or change a REST endpoint (schemas, repository method, service, route, tests) per project conventions.
---
1. `app/schemas/<resource>.py`: separate `XCreate` / `XUpdate` (all fields optional) / `XRead` (`from_attributes=True`); validation in `field_validator`.
2. `app/repositories/<resource>.py`: extend the `XRepository` Protocol first (methods are `async def`), then both implementations (`InMemoryXRepository`, `SqlAlchemyXRepository`); raise domain exceptions, never `HTTPException`.
3. If the change adds or changes a persisted field: update `app/models/<resource>.py` too, then `poetry run alembic revision --autogenerate -m "..."` and review the generated migration before committing it.
4. `app/services/<resource>.py`: business rules (existence checks, orchestration with S3/parsers later); raises domain exceptions; INFO log on state change, WARNING on rejected request, ids only.
5. `app/api/v1/routes/<resource>.py`: `async def` handlers calling the service via its `Annotated` dependency from `app/api/deps.py`, explicit `status_code` + `response_model`.
   201 create · 200 read/update · 204 delete · 404 missing · 409 conflict · 422 validation.
   Translate domain exceptions to `HTTPException` here only (`raise ... from None`). Register new routers in `app/api/v1/router.py`.
6. Tests: `tests/unit/` (service over in-memory repository), `tests/api/` (happy path + every error code), `tests/integration/` for new SQL behaviour.
7. Update the README and `ARCHITECTURE.md` endpoint tables, then run `/check`.
