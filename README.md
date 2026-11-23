# Genomic Variant Analysis Platform

REST API to upload VCF files, filter and annotate genomic variants and retrieve summaries.
Week 1 scope: projects. Architecture: [ARCHITECTURE.md](ARCHITECTURE.md).

You are on `week_1_implementation`: the full working week 1 solution. The step-by-step
walkthrough that builds it is [docs/week-01-implementation.md](docs/week-01-implementation.md).

## Branches

Each branch builds on the previous.

| Branch | Contains | Use it to |
|---|---|---|
| `main` | Task brief, architecture template, Claude Code configuration | Start from scratch and design the solution yourself |
| `week_1_setup` | `main` plus detailed guidance: concrete layer layout, filled-in architecture, extra Claude Code skill | Build week 1 with a clear target structure |
| `week_1_implementation` | `week_1_setup` plus the full working week 1 solution and a step-by-step walkthrough | Compare your work or study a reference implementation |

## Requirements

Python 3.15, Poetry 2.x, Docker with Compose v2, git.

## Run everything in Docker

```bash
docker compose up --build
```

Starts Postgres, applies migrations, then serves the API on http://127.0.0.1:8000
(interactive docs: http://127.0.0.1:8000/docs).

## Local development

```bash
poetry install
cp .env.example .env
docker compose up -d db
poetry run alembic upgrade head
poetry run uvicorn app.main:create_app --factory --reload
poetry run pre-commit install
```

## Tests

```bash
docker compose up -d test_db
poetry run pytest --cov                  # all tests, 80% coverage gate
poetry run pytest -m "not integration"   # fast, no database
```

## Migrations

```bash
poetry run alembic revision --autogenerate -m "describe the change"   # review the file!
poetry run alembic upgrade head
poetry run alembic downgrade -1
```

Rebuild the image (`docker compose up --build`) after adding a migration.

## API

| Method | Path | Success | Errors |
|---|---|---|---|
| POST | /api/v1/projects/ | 201 | 409, 422 |
| GET | /api/v1/projects/ | 200 | |
| DELETE | /api/v1/projects/{project_id}/ | 204 | 404, 422 |
| GET | /health | 200 | |

## Quality checks

`poetry run python scripts/check.py` runs the full gate: dash check, ruff lint and format,
`mypy app tests` (strict), pytest with the 80% coverage gate. CI
(`.github/workflows/ci.yml`) runs the same checks on every push and pull request.
