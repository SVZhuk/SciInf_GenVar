# Genomic Variant Analysis Platform
FastAPI + Pydantic v2 training project: upload VCF files, filter and annotate variants, REST summaries.
Async SQLAlchemy 2.0 + Postgres (AWS RDS), Alembic migrations, AWS S3, deploy to ECS Fargate.
Python 3.15 (latest stable) locally, in Docker and in CI; modern syntax (`datetime.UTC`, `X | None`) is fine.
Gold standard for trainees: clean, minimal, no speculative abstractions.
Docs: `ARCHITECTURE.md` (living architecture), `docs/week-NN-implementation.md` (weekly guides).

## Layers (never cross)
`api/v1/routes/` thin async HTTP → `services/` business rules → `repositories/` sole storage access.
`schemas/` hold Pydantic DTOs; `models/` hold SQLAlchemy table metadata only (no Session usage).
`api/deps.py` is DI wiring; `db/` owns engine, lifespan and per-request session; `core/` holds config + logging.
Routes never import repositories or `db/`; services and repositories never import FastAPI.
Domain exceptions are raised in services/repositories and mapped to HTTP status only in `api/errors.py` (one handler per base class).
Postgres for dev/test runs via `docker-compose.yml` (`db` + `test_db`).

## Rules
- Full type hints, `X | None`, Pydantic v2 API only. No `print`, no broad `except`.
- Logging: module loggers (`logging.getLogger(__name__)`), lazy `%s` args, ids not payloads,
  never log secrets, `DATABASE_URL` or request bodies.
- Tests: unit tests (in-memory repository, no IO) + API tests + Postgres integration tests;
  line coverage >= 80% gates `/check`; FIRST principles, one behaviour per test.
- Reuse existing patterns; ask before adding abstractions, dependencies or changing API shapes.
- Never weaken or delete a test to make it pass.
- No double-backtick notation in comments or code. Minimal comments.
- No em dash (U+2014) or en dash (U+2013) in code, comments, docstrings or docs; `/check` fails on them.
- Dependency management: Poetry (`pyproject.toml` + `poetry.lock`, in-project `.venv`). Always invoke
  python/pytest/ruff/mypy/alembic via `poetry run`; never bare `pip`, `uv` or `python -m venv`.
- Terraform in `infra/` follows the `terraform-aws` skill; run the `iac-guard` agent after infra/deploy/CI/container changes. `secret_guard` hook blocks credential files and secrets; never work around it.
- Formatting/lint autofix and a `pyright` type-check (`app/` only, standard mode) run via hook after every edit; don't restate style rules or reformat manually.
- Done = `/check` passes (`poetry run python scripts/check.py`; `mypy --strict` gates it; `pyright` is edit-time only). Many failures → `test-fixer` agent. Be brief; show diffs, not whole files.
