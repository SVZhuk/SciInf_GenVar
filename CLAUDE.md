# Genomic Variant Analysis Platform
FastAPI + Pydantic v2 training project: upload VCF files, filter and annotate variants, REST summaries.
Async SQLAlchemy 2.0 + Postgres (AWS RDS), Alembic migrations, AWS S3, deploy to ECS Fargate.
Python 3.15 (latest stable) locally, in Docker and in CI; modern syntax (`datetime.UTC`, `X | None`) is fine.
Clean, minimal code; no speculative abstractions.
Docs: `TASK.md` (week 1 brief and rubric), `ARCHITECTURE.md` (living architecture, kept up to date).

## Layers (never cross)
Route handlers → services → storage access, plus models, schemas and a database session module.
The concrete layout is described in `ARCHITECTURE.md` sections 3 and 4; follow it.
Route handlers stay thin (HTTP only); business rules live in services; only the storage layer talks
to the database. Models hold table definitions only; schemas hold request/response validation only.
Postgres for dev/test runs via `docker-compose.yml`.

## Rules
- Full type hints, `X | None`, Pydantic v2 API only. No `print`, no broad `except`.
- Logging: module loggers (`logging.getLogger(__name__)`), lazy `%s` args, ids not payloads,
  never log secrets, `DATABASE_URL` or request bodies.
- Tests: fast unit tests (no IO) + Postgres integration tests; line coverage >= 80%;
  FIRST principles, one behaviour per test.
- Reuse existing patterns; ask before adding abstractions, dependencies or changing API shapes.
- Never weaken or delete a test to make it pass.
- No double-backtick notation in comments or code. Minimal comments.
- No em dash (U+2014) or en dash (U+2013) in code, comments, docstrings or docs; `/check` fails on them.
- Dependency management: Poetry (`pyproject.toml` + `poetry.lock`, in-project `.venv`). Always invoke
  python/pytest/ruff/mypy/alembic via `poetry run`; never bare `pip`, `uv` or `python -m venv`.
- Terraform in `infra/` follows the `terraform-aws` skill; run the `iac-guard` agent after infra/deploy/CI/container changes. `secret_guard` hook blocks credential files and secrets; never work around it.
- Formatting/lint autofix and a `pyright` type-check (`app/` only, standard mode) run via hook after every edit; don't restate style rules or reformat manually.
- Done = `/check` passes (`poetry run python scripts/check.py`; `mypy --strict` gates it; `pyright` is edit-time only). Many failures → `test-fixer` agent. Be brief; show diffs, not whole files.
