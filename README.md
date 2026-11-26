# Genomic Variant Analysis Platform

REST API to upload VCF files, filter and annotate genomic variants and retrieve summaries.
Scope so far: projects (week 1), VCF and ClinVar annotation file uploads (week 2).
Architecture: [ARCHITECTURE.md](ARCHITECTURE.md).

You are on `week_2_implementation`: the full working solution up to week 2. The step-by-step
walkthroughs are [docs/week-01-implementation.md](docs/week-01-implementation.md) and
[docs/week-02-implementation.md](docs/week-02-implementation.md).

## Branches

Each branch builds on the previous.

| Branch | Contains | Use it to |
|---|---|---|
| `main` | Task brief, architecture template, Claude Code configuration | Start from scratch and design the solution yourself |
| `week_1_setup` | `main` plus detailed guidance: concrete layer layout, filled-in architecture, extra Claude Code skill | Build week 1 with a clear target structure |
| `week_1_implementation` | `week_1_setup` plus the full working week 1 solution and a step-by-step walkthrough | Compare your work or study a reference implementation |
| `week_2_implementation` | `week_1_implementation` plus VCF and annotation file endpoints and the week 2 walkthrough | Compare your week 2 work |

## Requirements

Python 3.15, Poetry 2.x, Docker with Compose v2, git.

## Run everything in Docker

```bash
docker compose up --build
```

Starts Postgres and a local S3 (moto server, bucket created by `s3-init`), applies migrations,
then serves the API on http://127.0.0.1:8000 (interactive docs: http://127.0.0.1:8000/docs).
Local S3 keeps objects in memory: they are gone after `docker compose down`.

## Local development

```bash
poetry install
cp .env.example .env
docker compose up -d db s3-init        # s3-init starts s3 and creates the bucket
poetry run alembic upgrade head
poetry run uvicorn app.main:create_app --factory --reload --env-file .env
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
| POST | /api/v1/projects/{project_id}/vcf/ (multipart `file`: .vcf, .vcf.gz) | 201 + Location | 404, 413, 422 |
| GET | /api/v1/projects/{project_id}/vcf/ | 200 | 404 |
| GET | /api/v1/projects/{project_id}/vcf/{vcf_id}?limit=&offset= | 200 | 404, 422 |
| DELETE | /api/v1/projects/{project_id}/vcf/{vcf_id} | 204 | 404 |
| POST | /api/v1/projects/{project_id}/annotation/ (multipart `file`: .txt, .tsv, optionally .gz) | 201 | 404, 413, 422 |
| GET | /api/v1/projects/{project_id}/annotation/ | 200 | 404 |
| DELETE | /api/v1/projects/{project_id}/annotation/{annotation_id} | 204 | 404 |
| GET | /health | 200 | |

Example upload:

```bash
curl -F file=@datasets/calls.vcf.gz http://127.0.0.1:8000/api/v1/projects/<project_id>/vcf/
```

`scripts/generate_test_datasets.sh` fills the git-ignored `datasets/` folder with files to try:
a small synthetic VCF, slices of the real ClinVar summary (full and simplified formats), the
ClinVar VCF (no AF key), a 1000 Genomes chr22 region with AF (needs `bcftools`), and files under
`datasets/rejected/` that must return 422. Existing files are kept; `FORCE=1` downloads again.

## Quality checks

`poetry run python scripts/check.py` runs the full gate: dash check, ruff lint and format,
`mypy app tests` (strict), pytest with the 80% coverage gate. CI
(`.github/workflows/ci.yml`) runs the same checks on every push and pull request.
