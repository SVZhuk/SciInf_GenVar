# Week 1: Project foundation and the Projects API

Goal: a running FastAPI service with a Postgres-backed `projects` resource, migrations, Docker,
tests (coverage at least 80%), pre-commit hooks and a GitHub Actions pipeline.
Read [ARCHITECTURE.md](../ARCHITECTURE.md) first; this guide builds the week 1 slice of it.

Every code block below is complete. Type it (or copy it) exactly, run the check at the end of each
step, and commit once the step works.

## Task coverage

| Course task | Where |
|---|---|
| 1.1 Git repository on GitHub | Step 1 |
| 1.2 Project structure (routes, services, models, schemas, database session) | Step 1, built in steps 3 to 7 |
| 1.3 Virtual environment with Poetry | Step 2 |
| 1.4 Core dependencies, base FastAPI application | Step 3 |
| 1.5 Docker and Docker Compose for local development | Step 9 |
| 1.6 README.md with setup instructions | Step 13 |
| 2.1 GitHub Actions: lint, format, test stages on every push and pull request | Step 12 |
| 2.1 pre-commit hooks: ruff, trailing whitespace, end-of-file fixer | Step 11 |
| 3 `POST /projects/`, `GET /projects/`, `DELETE /projects/{project_id}/` | Step 7 (under `/api/v1`) |
| 4.1 Schema for projects, vcf_files, variants, annotation_files, annotations | Design: [ARCHITECTURE.md](../ARCHITECTURE.md#6-data-model); implemented: `projects` (step 5) |
| 4.3 Endpoints on PostgreSQL via SQLAlchemy async ORM | Steps 5 to 7 |
| 4.4 SQLAlchemy models | Step 5 |
| 4.5 Pydantic request/response schemas | Step 5 |
| 4.6 Alembic migrations (optional, done) | Step 8 |
| Beyond the brief: logging, 80% coverage gate, mypy | Steps 4, 10, 12 |

## Definition of done

- [ ] `poetry init` sets up `.venv/` from `poetry.lock`
- [ ] `docker compose up --build` starts db, runs migrations, serves the API on :8000
- [ ] `POST /api/v1/projects/`, `GET /api/v1/projects/`, `DELETE /api/v1/projects/{project_id}/` work
- [ ] `alembic upgrade head` and `alembic downgrade base` both run cleanly
- [ ] `poetry run pytest --cov` passes with coverage at least 80%
- [ ] `poetry run pre-commit run --all-files` and `poetry run mypy app tests` pass
- [ ] GitHub Actions is green on push and on pull request
- [ ] `README.md` lets a new person run everything without asking you

## Prerequisites

| Tool | Version | Check |
|---|---|---|
| Python | 3.15 (latest stable) | `python3 --version` |
| Poetry | 2.x | `poetry --version` (install: `pipx install poetry`) |
| Docker + Compose v2 | recent | `docker compose version` |
| git | any | `git --version` |

The project targets the latest stable Python, 3.15, everywhere (local, Docker, CI). If your system
Python is older, install 3.15 (for example with pyenv or uv) and point Poetry at it:
`poetry env use /path/to/python3.15`.

---

## Step 1. Project structure

Target layout at the end of the week:

```text
.
├── app/
│   ├── main.py                    application factory, /health
│   ├── core/
│   │   ├── config.py              Settings from environment / .env
│   │   ├── exceptions.py          domain errors
│   │   └── logging.py             logging setup, request log middleware
│   ├── db/
│   │   ├── base.py                Declarative Base + constraint naming convention
│   │   └── session.py             engine lifecycle, one session per request
│   ├── models/                    SQLAlchemy tables (what Postgres stores)
│   │   ├── __init__.py            imports every model
│   │   └── project.py
│   ├── schemas/                   Pydantic DTOs (what the API accepts and returns)
│   │   └── project.py
│   ├── repositories/              the only code that talks to storage
│   │   └── project.py
│   ├── services/                  business rules
│   │   └── project.py
│   └── api/
│       ├── deps.py                dependency injection wiring
│       └── v1/
│           ├── router.py          /api/v1 prefix
│           └── routes/
│               └── projects.py    HTTP handlers
├── alembic/                       migrations
├── tests/
│   ├── conftest.py
│   ├── unit/                      no IO, milliseconds
│   ├── api/                       HTTP in process, in-memory storage
│   └── integration/               real Postgres (test_db)
├── .github/workflows/ci.yml
├── .pre-commit-config.yaml
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── pyproject.toml
├── poetry.lock
├── poetry.toml
├── .env.example
├── .gitignore
├── .dockerignore
└── README.md
```

Each layer has one job. A request flows `routes -> services -> repositories -> database`;
nothing calls "upwards".

| Layer | Job | Must not |
|---|---|---|
| `api/v1/routes/` | Map HTTP to service calls, domain errors to status codes | import repositories or `db/` |
| `services/` | Business rules (later: VCF parsing, S3 uploads) | import FastAPI |
| `repositories/` | Read and write storage | import FastAPI, contain business rules |
| `schemas/` | Validate input, shape output | know about storage |
| `models/` | Describe tables | open sessions or run queries |
| `api/deps.py` | Build services with their dependencies | contain logic |

Create the folders and empty package markers:

```bash
mkdir -p app/core app/db app/models app/schemas app/repositories app/services \
         app/api/v1/routes tests/unit tests/api tests/integration
touch app/__init__.py app/core/__init__.py app/db/__init__.py app/schemas/__init__.py \
      app/repositories/__init__.py app/services/__init__.py app/api/__init__.py \
      app/api/v1/__init__.py app/api/v1/routes/__init__.py \
      tests/__init__.py tests/unit/__init__.py tests/api/__init__.py tests/integration/__init__.py
```

### Git repository

Write `.gitignore` before the first commit, so the virtual environment, secrets and caches never
enter the history (removing a committed `.env` later does not remove it from old commits):

`.gitignore`:

```text
__pycache__/
.venv/
.env
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
coverage.xml
htmlcov/
.claude/logs/
```

On GitHub, create an empty repository (no README, no .gitignore, no license, so the first push
does not conflict). Then:

```bash
git init -b main
git add .
git commit -m "chore: project skeleton"
git remote add origin git@github.com:<your-user>/genomic-variant-analysis.git
git push -u origin main
```

From here on, work on a branch per step and merge through a pull request, so CI (step 12) checks
every change before it reaches `main`:

```bash
git switch -c feat/poetry-setup
# ... work, commit ...
git push -u origin feat/poetry-setup    # open a pull request on GitHub
```

## Step 2. Virtual environment with Poetry

```bash
poetry config virtualenvs.in-project true --local   # writes poetry.toml: .venv/ lives in the repo
poetry init --no-interaction --name genomic-variant-analysis \
  --description "Genomic Variant Analysis Platform API" --python ">=3.15,<4.0"
```

This is an application, not a library, so tell Poetry not to package it. Append to `pyproject.toml`:

```toml
[tool.poetry]
package-mode = false
```

Remove the `authors` and `[build-system]` blocks that `poetry init` generated; an unpackaged
application needs neither.

Why in-project: editors, pyright and the Dockerfile all find the interpreter at `.venv/bin/python`.

## Step 3. Dependencies and the base application

```bash
poetry add fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg alembic pydantic-settings
poetry add --group dev ruff mypy pyright pytest pytest-asyncio pytest-cov httpx pre-commit
```

| Package | Why |
|---|---|
| fastapi, uvicorn | Web framework and ASGI server |
| sqlalchemy[asyncio], asyncpg | Async ORM and the Postgres driver it uses |
| alembic | Schema migrations |
| pydantic-settings | Typed configuration from environment variables |
| ruff, mypy, pyright | Lint + format, strict type check, editor type check |
| pytest, pytest-asyncio, pytest-cov, httpx | Async tests, coverage, in-process HTTP client |
| pre-commit | Run ruff and whitespace fixers before every commit |

Append tool configuration to `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py315"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "RUF", "ANN", "PT", "T20", "BLE"]

[tool.ruff.lint.per-file-ignores]
"scripts/*" = ["T20"]

[tool.mypy]
python_version = "3.15"
strict = true
plugins = ["pydantic.mypy"]

[tool.pyright]
include = ["app"]
pythonVersion = "3.15"
typeCheckingMode = "standard"
venvPath = "."
venv = ".venv"

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-q --strict-markers"
markers = ["integration: needs the Postgres test database (docker compose up -d test_db)"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"

[tool.coverage.run]
source = ["app"]
branch = true

[tool.coverage.report]
fail_under = 80
show_missing = true
skip_covered = true
```

Notes:
- `T20` bans `print`, `BLE` bans `except Exception`, `ANN` requires type hints.
- One event loop for the whole test session: the session-scoped database engine and every test
  must share it, otherwise asyncpg raises "attached to a different loop".
- The 80% threshold lives in one place (`[tool.coverage.report]`) and applies whenever pytest runs
  with `--cov`.

### Settings

`app/core/config.py`:

```python
"""Application settings, read from environment variables or a local .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    log_level: LogLevel = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  (filled from the environment)
```

`SecretStr` prints as `**********`, so the database password cannot leak through a log line or a
traceback by accident. Read the real value only where it is needed: `.get_secret_value()`.

`.env.example` (committed; `.env` itself never is):

```dotenv
# Copy to .env and adjust; .env is git-ignored. Values match the local docker-compose.yml databases.
DATABASE_URL=postgresql+asyncpg://app:app@localhost:5434/gva
TEST_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5433/gva_test
LOG_LEVEL=INFO
```

```bash
cp .env.example .env
```

### Application factory

`app/main.py` (the routers and database pieces it imports are written in steps 4 to 7; until
then, comment out those lines to try `/health` on its own):

```python
"""Application factory. Run with: poetry run uvicorn app.main:create_app --factory --reload"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import router as v1_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_requests
from app.db.session import database_lifespan


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)
    async with database_lifespan(app, settings):
        yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Genomic Variant Analysis API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings or get_settings()
    app.middleware("http")(log_requests)
    app.include_router(v1_router)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

Why a factory with an optional `settings` argument: there is no module-level `app` that reads the
environment at import time, and tests build a fresh app with explicit test settings. Uvicorn calls
the factory itself (`--factory`).

## Step 4. Logging

`app/core/logging.py`:

```python
"""Logging setup and per-request access log."""

import logging
import logging.config
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

logger = logging.getLogger("app.request")


def configure_logging(level: str) -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"default": {"format": LOG_FORMAT}},
            "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "default"}},
            "root": {"handlers": ["console"], "level": level},
            "loggers": {"uvicorn.access": {"level": "WARNING"}},
        }
    )


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Log method, path, status and duration; never query strings or bodies."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    level = logging.INFO
    if response.status_code >= 500:
        level = logging.ERROR
    elif response.status_code >= 400:
        level = logging.WARNING
    logger.log(
        level,
        "%s %s -> %d (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response
```

Logging rules for the whole project:

| Level | Use for | Example |
|---|---|---|
| DEBUG | Storage detail useful while developing | `Fetched 3 project rows` |
| INFO | Successful state changes and lifecycle | `Project created project_id=...`, `Database engine started` |
| WARNING | Request rejected for a business reason, 4xx | `Project not deleted: project_id=... not found` |
| ERROR | Server faults, 5xx | request log line for a 500 |

- One logger per module: `logger = logging.getLogger(__name__)`. The name shows where a line came from.
- Lazy formatting: `logger.info("project_id=%s", project_id)`, never f-strings (the string is only built if
  the level is enabled).
- Log identifiers, never payloads: no request bodies, no query strings, no `DATABASE_URL`, no
  passwords. Later weeks add VCF content, which may be patient data: it must never reach a log.
- Logging is configured once, in the lifespan, so tests that do not start the lifespan keep pytest's
  own log capture.
- uvicorn's access log is silenced to WARNING because `log_requests` replaces it with a line that
  includes the duration.

## Step 5. Database layer and the projects schema

Only the `projects` table is built this week. The full target schema (`vcf_files`, `variants`,
`annotation_files`, `annotations`) is in [ARCHITECTURE.md](../ARCHITECTURE.md#6-data-model).

`projects` columns:

| Column | Type | Null | Set by |
|---|---|---|---|
| `project_id` | `uuid`, primary key | no | application (`uuid4`) |
| `name` | `varchar(100)`, unique | no | client |
| `lead_scientist` | `varchar(100)` | no | client |
| `description` | `text` | yes | client |
| `created_at` | `timestamptz`, default `now()` | no | database |
| `completed_at` | `timestamptz` | yes, NULL while the project runs | later "complete" use case |

### Naming conventions

The project follows these rules for every table:

| Rule | Example | Why |
|---|---|---|
| snake_case, lower case | `lead_scientist` | Postgres folds unquoted names to lower case; no quoting needed |
| Table names are plural nouns | `projects`, `vcf_files` | A table holds many rows; matches the REST paths |
| Primary key is `<entity>_id` | `projects.project_id` | Self-describing in joins; a foreign key has the same name as the key it references |
| Foreign key is `<referenced entity>_id` | `vcf_files.project_id` | You can see what it points to |
| No table prefix on other columns | `name`, not `project_name` | The table already says what it describes: `projects.name` |
| Timestamps end in `_at`, timezone-aware | `created_at`, `completed_at` | `completed` could be a boolean; `completed_at` cannot |
| Booleans start with `is_` or `has_` | `is_archived` | Reads as a yes/no question |
| No reserved words, no abbreviations | `description`, not `desc` | `desc` is an SQL keyword |

Whether the primary key is `id` or `project_id` is a style choice: ORMs such as Django and Rails
default to `id`, while SQL style guides (for example sqlstyle.guide) prefer `<entity>_id`. Both
work. Pick one and use it everywhere; this project uses `<entity>_id`.

`app/db/base.py`:

```python
"""Declarative base shared by all models; naming convention gives stable constraint names."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

Without a naming convention Postgres invents constraint names, and migrations that drop or alter a
constraint cannot refer to it reliably. With it, the primary key of `projects` is always called
`pk_projects` and the unique constraint on `projects.name` is `uq_projects_name`.

`app/db/session.py`:

```python
"""Engine lifecycle and one database session (one transaction) per request."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def database_lifespan(app: FastAPI, settings: Settings) -> AsyncIterator[None]:
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    logger.info("Database engine started")
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("Database engine disposed")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Unit of Work: commit if the request succeeds, roll back if anything raises."""
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session, session.begin():
        yield session
```

- One engine (connection pool) per process, created at startup and disposed at shutdown.
- One session per request. `session.begin()` commits when the request finishes without error and
  rolls back if anything raised, including an `HTTPException` from a route.
- `expire_on_commit=False` keeps loaded attributes readable after commit, which async code needs
  (an expired attribute would trigger lazy IO outside an `await`).

`app/models/project.py`:

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProjectModel(Base):
    __tablename__ = "projects"

    project_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    lead_scientist: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

`Mapped[str]` means NOT NULL, `Mapped[str | None]` means nullable: the type hint is the schema.
`project_id` is generated by the application (`uuid4`), so ids are unique without a round trip and
never reveal how many projects exist. `created_at` is set by Postgres (`now()`), and SQLAlchemy reads
it back in the same INSERT through `RETURNING`. `completed_at` stays NULL while the project runs;
setting it is a later use case (a "complete project" endpoint), so it is not part of the create
payload.

`app/models/__init__.py`:

```python
"""Import every model here, so importing Base from this package registers all tables."""

from app.db.base import Base
from app.models.project import ProjectModel

__all__ = ["Base", "ProjectModel"]
```

Alembic and the test fixtures import `Base` from `app.models`, never from `app.db.base`.

A table is added to `Base.metadata` only when its model class is executed, that is, when the model
module is imported. `app.db.base` defines `Base` with an empty `MetaData` and imports no models.
`app.models` is a package, so Python runs its `__init__.py` first, and that file imports every
model; after `from app.models import Base`, the metadata is complete.

| Import | `Base.metadata` contains |
|---|---|
| `from app.db.base import Base` | nothing, unless something else imported the models |
| `from app.models import Base` | every model listed in `app/models/__init__.py` |

Alembic autogenerate and `Base.metadata.create_all` in the test fixtures read only this metadata.
With an empty one, autogenerate writes an empty migration and the tests find no tables. Add each
new model to `app/models/__init__.py`. Model modules import `Base` from `app.db.base`, never from
`app.models`, which would be a circular import.

### Pydantic schemas

`app/schemas/project.py`:

```python
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ProjectCreate(BaseModel):
    name: ShortText
    lead_scientist: ShortText
    description: Annotated[str | None, Field(max_length=2000)] = None


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    created_at: datetime
    completed_at: datetime | None
```

- `ProjectCreate` has no `project_id`, `created_at` or `completed_at`: clients cannot set
  server-owned fields (unknown fields in the request body are ignored).
- `ProjectRead` inherits the client fields and adds the server-owned ones (DRY);
  `from_attributes=True` lets it read a `ProjectModel` instance directly.
- One `ShortText` type serves both `name` and `lead_scientist` (DRY): `"  BRCA cohort  "` is stored
  as `"BRCA cohort"`, and an empty or too long value is a 422.

### Domain errors

`app/core/exceptions.py`:

```python
"""Domain errors: raised by services and repositories, mapped to HTTP status codes in routes."""

from uuid import UUID


class ProjectNotFoundError(Exception):
    def __init__(self, project_id: UUID) -> None:
        super().__init__(f"Project {project_id} not found")
        self.project_id = project_id


class ProjectNameConflictError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Project name {name!r} already exists")
        self.name = name
```

They live in `core/` because both repositories (duplicate name) and services (not found) raise
them, and routes catch them without importing the storage layer.

## Step 6. Repository and service

`app/repositories/project.py`:

```python
"""Data access for projects (Repository pattern): the only code that touches storage."""

import logging
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProjectNameConflictError
from app.models import ProjectModel
from app.schemas.project import ProjectCreate

logger = logging.getLogger(__name__)

UNIQUE_NAME_CONSTRAINT = "uq_projects_name"


class ProjectRepository(Protocol):
    async def add(self, data: ProjectCreate) -> ProjectModel: ...
    async def list_all(self) -> list[ProjectModel]: ...
    async def get(self, project_id: UUID) -> ProjectModel | None: ...
    async def delete(self, project: ProjectModel) -> None: ...


class SqlAlchemyProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: ProjectCreate) -> ProjectModel:
        project = ProjectModel(**data.model_dump())
        self._session.add(project)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if UNIQUE_NAME_CONSTRAINT in str(exc.orig):
                raise ProjectNameConflictError(data.name) from exc
            raise
        logger.debug("Inserted project row project_id=%s", project.project_id)
        return project

    async def list_all(self) -> list[ProjectModel]:
        result = await self._session.scalars(
            select(ProjectModel).order_by(ProjectModel.created_at, ProjectModel.project_id)
        )
        projects = list(result)
        logger.debug("Fetched %d project rows", len(projects))
        return projects

    async def get(self, project_id: UUID) -> ProjectModel | None:
        return await self._session.get(ProjectModel, project_id)

    async def delete(self, project: ProjectModel) -> None:
        await self._session.delete(project)
        await self._session.flush()
        logger.debug("Deleted project row project_id=%s", project.project_id)


class InMemoryProjectRepository:
    """Dict-backed storage for fast tests: O(1) lookup by id and O(1) duplicate-name check."""

    def __init__(self) -> None:
        self._projects: dict[UUID, ProjectModel] = {}
        self._names: set[str] = set()

    async def add(self, data: ProjectCreate) -> ProjectModel:
        if data.name in self._names:
            raise ProjectNameConflictError(data.name)
        project = ProjectModel(
            project_id=uuid4(), created_at=datetime.now(UTC), **data.model_dump()
        )
        self._projects[project.project_id] = project
        self._names.add(project.name)
        return project

    async def list_all(self) -> list[ProjectModel]:
        return list(self._projects.values())

    async def get(self, project_id: UUID) -> ProjectModel | None:
        return self._projects.get(project_id)

    async def delete(self, project: ProjectModel) -> None:
        del self._projects[project.project_id]
        self._names.discard(project.name)
```

- `ProjectRepository` is a `Protocol`: any class with these methods fits, no inheritance needed.
  The service depends on this interface, not on SQLAlchemy (Dependency Inversion).
- Name uniqueness is enforced by the database (`uq_projects_name`), not by a "check then insert"
  query, which would race under concurrent requests. Only that constraint becomes a domain error;
  any other integrity failure re-raises unchanged.
- `InMemoryProjectRepository` keeps a `dict` keyed by `project_id` and a `set` of names, so every
  operation, including the duplicate check, is O(1). Python dicts keep insertion order, which
  equals creation order. It backs the unit and API tests.
- Listing orders by `created_at`, then `project_id` as a tie-breaker: Postgres `now()` is the
  transaction start time, so rows inserted in one transaction share a timestamp.
- The method is called `list_all`, not `list`: a method named `list` would shadow the builtin inside
  the class body and break annotations such as `list[ProjectModel]`.

`app/services/project.py`:

```python
"""Business rules for projects (Service Layer); storage is reached only through the repository."""

import logging
from uuid import UUID

from app.core.exceptions import ProjectNameConflictError, ProjectNotFoundError
from app.models import ProjectModel
from app.repositories.project import ProjectRepository
from app.schemas.project import ProjectCreate

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    async def create_project(self, data: ProjectCreate) -> ProjectModel:
        try:
            project = await self._repository.add(data)
        except ProjectNameConflictError:
            logger.warning("Project not created: name already exists")
            raise
        logger.info("Project created project_id=%s", project.project_id)
        return project

    async def list_projects(self) -> list[ProjectModel]:
        return await self._repository.list_all()

    async def delete_project(self, project_id: UUID) -> None:
        project = await self._repository.get(project_id)
        if project is None:
            logger.warning("Project not deleted: project_id=%s not found", project_id)
            raise ProjectNotFoundError(project_id)
        await self._repository.delete(project)
        logger.info("Project deleted project_id=%s", project_id)
```

This week the service is thin. It earns its place from week 2: uploading a VCF file means
"store the file in S3, parse it, insert variants" in one use case, and that orchestration belongs
here, not in a route and not in a repository.

## Step 7. Routes and dependency injection

`app/api/deps.py`:

```python
"""Dependency Injection wiring: the only place that picks concrete implementations."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.repositories.project import SqlAlchemyProjectRepository
from app.services.project import ProjectService

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


def get_project_service(session: SessionDep) -> ProjectService:
    return ProjectService(SqlAlchemyProjectRepository(session))


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
```

`scope="function"` closes the session (and commits) before the response is sent, so a failed
commit becomes a 500 instead of a 201 for data that was never saved.

`app/api/v1/routes/projects.py`:

```python
"""/projects resource: thin async handlers, HTTP concerns only."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ProjectServiceDep
from app.core.exceptions import ProjectNameConflictError, ProjectNotFoundError
from app.schemas.project import ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, service: ProjectServiceDep) -> ProjectRead:
    try:
        project = await service.create_project(payload)
    except ProjectNameConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    return ProjectRead.model_validate(project)


@router.get("/", response_model=list[ProjectRead])
async def list_projects(service: ProjectServiceDep) -> list[ProjectRead]:
    return [ProjectRead.model_validate(project) for project in await service.list_projects()]


@router.delete("/{project_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: UUID, service: ProjectServiceDep) -> None:
    try:
        await service.delete_project(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
```

`app/api/v1/router.py`:

```python
"""Version prefix: every v1 resource router is mounted here."""

from fastapi import APIRouter

from app.api.v1.routes import projects

router = APIRouter(prefix="/api/v1")
router.include_router(projects.router)
```

| Method | Path | Success | Errors |
|---|---|---|---|
| POST | `/api/v1/projects/` | 201 + project | 409 duplicate name, 422 invalid body |
| GET | `/api/v1/projects/` | 200 + list, oldest first | |
| DELETE | `/api/v1/projects/{project_id}/` | 204, empty body | 404 unknown id, 422 not a UUID |
| GET | `/health` | 200 `{"status": "ok"}` | |

The paths keep the trailing slash from the specification. A request without it
(`/api/v1/projects`) gets a 307 redirect to the slash version; clients should use the exact path.
The `/api/v1` prefix lets a future `/api/v2` live next to v1 without breaking existing clients.

## Step 8. Alembic migrations

```bash
poetry run alembic init -t async alembic
```

In `alembic.ini`:
1. Uncomment the `file_template` line that starts with `%%(year)d_%%(month).2d_%%(day).2d`, so
   revision files sort by date.
2. Leave `sqlalchemy.url` as the placeholder; `env.py` sets the real URL from `Settings`.
3. Format generated revisions automatically. Directly under `[post_write_hooks]` add:

```ini
hooks = ruff_lint, ruff_format
ruff_lint.type = module
ruff_lint.module = ruff
ruff_lint.options = check --fix REVISION_SCRIPT_FILENAME
ruff_format.type = module
ruff_format.module = ruff
ruff_format.options = format REVISION_SCRIPT_FILENAME
```

Replace `alembic/env.py` with:

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Settings is the single source of truth for the URL; alembic.ini keeps only a placeholder.
# Escape % so ConfigParser interpolation does not choke on URL-encoded passwords.
config.set_main_option(
    "sqlalchemy.url", get_settings().database_url.get_secret_value().replace("%", "%%")
)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
```

Generate and apply the first migration (needs the `db` container from step 9 running):

```bash
docker compose up -d db
poetry run alembic revision --autogenerate -m "create projects table"
```

Always read the generated file before committing it. It should create `projects` with the
primary key `pk_projects` and the unique constraint `uq_projects_name`:

```python
def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("lead_scientist", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("project_id", name=op.f("pk_projects")),
        sa.UniqueConstraint("name", name=op.f("uq_projects_name")),
    )


def downgrade() -> None:
    op.drop_table("projects")
```

```bash
poetry run alembic upgrade head      # apply
poetry run alembic downgrade base    # roll everything back
poetry run alembic upgrade head      # apply again
poetry run alembic check             # "No new upgrade operations detected." = models match the DB
```

Rule: the schema changes only through migrations. Never call `Base.metadata.create_all()` against
the dev or production database (tests are the one exception, on a throwaway database).

## Step 9. Docker and Docker Compose

`Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1
# Multi-stage build: Poetry only in the builder, slim non-root runtime.

FROM python:3.15-slim AS builder
ENV POETRY_VERSION=2.4.3 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    PIP_NO_CACHE_DIR=1
RUN pip install "poetry==${POETRY_VERSION}"
WORKDIR /app
# Dependencies first: this layer is rebuilt only when pyproject.toml or poetry.lock change.
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root

FROM python:3.15-slim AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

- Two stages: Poetry and build tools never reach the runtime image, which only gets `.venv/` and code.
- Dependencies are copied and installed before the code, so editing `app/` does not reinstall them.
- Fixed non-root UID 10001: ECS and Kubernetes can enforce "run as non-root".

`.dockerignore`:

```text
.env
.venv
.git
.github
.claude
**/__pycache__
.pytest_cache
.mypy_cache
.ruff_cache
.coverage
coverage.xml
htmlcov
tests
docs
scripts
*.md
```

`docker-compose.yml`:

```yaml
# Full stack:        docker compose up --build        (db, then migrate, then api on :8000)
# Live reload:       docker compose up --build --watch
# Dev database only: docker compose up -d db          (run the API locally with Poetry)
# Test database:     docker compose up -d test_db     (needed by tests marked integration)
# Local development credentials only; real environments inject DATABASE_URL from a secret store.
x-api: &api
  build: .
  image: gva-api:local
  environment:
    DATABASE_URL: postgresql+asyncpg://app:app@db:5432/gva
    LOG_LEVEL: ${LOG_LEVEL:-INFO}

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: gva
    ports:
      - "127.0.0.1:5434:5432"
    volumes:
      - db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d gva"]
      interval: 5s
      timeout: 5s
      retries: 5

  test_db:
    profiles: [test]
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: gva_test
    ports:
      - "127.0.0.1:5433:5432"
    tmpfs:
      - /var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d gva_test"]
      interval: 5s
      timeout: 5s
      retries: 5

  migrate:
    <<: *api
    command: ["alembic", "upgrade", "head"]
    depends_on:
      db:
        condition: service_healthy

  api:
    <<: *api
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      migrate:
        condition: service_completed_successfully
    develop:
      watch:
        - action: sync+restart
          path: ./app
          target: /app/app
        - action: rebuild
          path: ./poetry.lock

volumes:
  db_data:
```

- Start order is enforced: `db` healthy, then `migrate` runs and exits 0, then `api` starts.
- `x-api` is a YAML anchor: `migrate` and `api` share one image and one environment (DRY).
- Ports bind to `127.0.0.1` only, so the databases are never reachable from your network. Host port
  5434 avoids clashing with a locally installed Postgres on 5432.
- `test_db` keeps its data in `tmpfs` (RAM): fast, and empty after every restart.
- `test_db` is in the `test` profile, so `docker compose up` skips it; naming it explicitly
  (`docker compose up -d test_db`) still starts it.

Try it:

```bash
docker compose up --build -d --wait api
curl -s -X POST http://127.0.0.1:8000/api/v1/projects/ \
  -H 'content-type: application/json' \
  -d '{"name": "BRCA cohort", "lead_scientist": "Rosalind Franklin", "description": "WES"}'
curl -s http://127.0.0.1:8000/api/v1/projects/
docker compose logs api        # one log line per request, with status and duration
docker compose down            # add -v to also delete the database volume
```

Or run the API locally against the containerised database:

```bash
docker compose up -d db
poetry run alembic upgrade head
poetry run uvicorn app.main:create_app --factory --reload
# open http://127.0.0.1:8000/docs
```

## Step 10. Tests

Three layers, from fastest to most realistic:

| Folder | What runs | Storage | Speed |
|---|---|---|---|
| `tests/unit/` | schemas, in-memory repository, service | `InMemoryProjectRepository` | ms |
| `tests/api/` | real app over HTTP in process (httpx `ASGITransport`) | `InMemoryProjectRepository` | ms |
| `tests/integration/` | SQL repository, full stack with lifespan | Postgres `test_db` | ~1 s |

FIRST principles, and how this suite meets them:

| Principle | Meaning | How |
|---|---|---|
| Fast | Runs in seconds, so you run it all the time | Unit and API layers do no IO |
| Independent | Any order, any subset | Fresh repository and app per test; every database test runs in a transaction that is rolled back |
| Repeatable | Same result everywhere | Explicit test settings (`_env_file=None`), no reliance on `.env`, wall clock or test order |
| Self-validating | Pass or fail, no reading output | Only `assert`; `print` is banned by ruff |
| Timely | Written with the code | Each step's tests land in the same commit as the step |

Each test checks one behaviour and follows Arrange, Act, Assert (blank lines separate the three).

`tests/conftest.py`:

```python
"""Shared fixtures: settings that never read .env, and an in-memory service per test."""

import os

import pytest

from app.core.config import Settings
from app.repositories.project import InMemoryProjectRepository
from app.services.project import ProjectService

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://app:app@localhost:5433/gva_test"
)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(_env_file=None, database_url=TEST_DATABASE_URL)


@pytest.fixture
def repository() -> InMemoryProjectRepository:
    return InMemoryProjectRepository()


@pytest.fixture
def service(repository: InMemoryProjectRepository) -> ProjectService:
    return ProjectService(repository)
```

`tests/unit/test_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from app.schemas.project import ProjectCreate


def test_text_fields_are_stripped() -> None:
    project = ProjectCreate(name="  BRCA cohort  ", lead_scientist="  Rosalind Franklin  ")

    assert project.name == "BRCA cohort"
    assert project.lead_scientist == "Rosalind Franklin"


def test_description_is_optional() -> None:
    project = ProjectCreate(name="BRCA cohort", lead_scientist="Rosalind Franklin")

    assert project.description is None


@pytest.mark.parametrize("field", ["name", "lead_scientist"])
@pytest.mark.parametrize("value", ["", "   ", "x" * 101])
def test_invalid_required_text_is_rejected(field: str, value: str) -> None:
    data = {"name": "BRCA cohort", "lead_scientist": "Rosalind Franklin", field: value}

    with pytest.raises(ValidationError):
        ProjectCreate.model_validate(data)


def test_client_cannot_set_server_fields() -> None:
    project = ProjectCreate.model_validate(
        {
            "name": "BRCA cohort",
            "lead_scientist": "Rosalind Franklin",
            "project_id": "x",
            "completed_at": "2026-01-01T00:00:00Z",
        }
    )

    assert set(project.model_dump()) == {"name", "lead_scientist", "description"}
```

`tests/unit/test_in_memory_repository.py`:

```python
from uuid import uuid4

import pytest

from app.core.exceptions import ProjectNameConflictError
from app.repositories.project import InMemoryProjectRepository
from app.schemas.project import ProjectCreate


def new_project(name: str = "BRCA cohort") -> ProjectCreate:
    return ProjectCreate(name=name, lead_scientist="Rosalind Franklin")


async def test_add_sets_server_owned_fields(repository: InMemoryProjectRepository) -> None:
    project = await repository.add(new_project())

    assert project.project_id is not None
    assert project.created_at.tzinfo is not None
    assert project.completed_at is None


async def test_add_generates_unique_project_ids(repository: InMemoryProjectRepository) -> None:
    first = await repository.add(new_project("first"))
    second = await repository.add(new_project("second"))

    assert first.project_id != second.project_id


async def test_add_rejects_duplicate_name(repository: InMemoryProjectRepository) -> None:
    await repository.add(new_project())

    with pytest.raises(ProjectNameConflictError):
        await repository.add(new_project())


async def test_get_unknown_id_returns_none(repository: InMemoryProjectRepository) -> None:
    assert await repository.get(uuid4()) is None


async def test_delete_frees_the_name(repository: InMemoryProjectRepository) -> None:
    project = await repository.add(new_project())

    await repository.delete(project)

    assert await repository.get(project.project_id) is None
    assert (await repository.add(new_project())).name == "BRCA cohort"
```

`tests/unit/test_project_service.py`:

```python
import logging
from uuid import uuid4

import pytest

from app.core.exceptions import ProjectNameConflictError, ProjectNotFoundError
from app.schemas.project import ProjectCreate
from app.services.project import ProjectService


def new_project(name: str = "BRCA cohort") -> ProjectCreate:
    return ProjectCreate(name=name, lead_scientist="Rosalind Franklin")


async def test_create_project_logs_id(
    service: ProjectService, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        project = await service.create_project(new_project())

    assert f"Project created project_id={project.project_id}" in caplog.messages


async def test_create_duplicate_raises_and_warns(
    service: ProjectService, caplog: pytest.LogCaptureFixture
) -> None:
    await service.create_project(new_project())

    with pytest.raises(ProjectNameConflictError):
        await service.create_project(new_project())

    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_list_projects_in_creation_order(service: ProjectService) -> None:
    first = await service.create_project(new_project("first"))
    second = await service.create_project(new_project("second"))

    assert await service.list_projects() == [first, second]


async def test_delete_project_removes_it(service: ProjectService) -> None:
    project = await service.create_project(new_project())

    await service.delete_project(project.project_id)

    assert await service.list_projects() == []


async def test_delete_unknown_project_raises_and_warns(
    service: ProjectService, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(ProjectNotFoundError):
        await service.delete_project(uuid4())

    assert any(record.levelno == logging.WARNING for record in caplog.records)
```

`tests/api/conftest.py`:

```python
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_project_service
from app.core.config import Settings
from app.main import create_app
from app.services.project import ProjectService


@pytest_asyncio.fixture
async def client(settings: Settings, service: ProjectService) -> AsyncIterator[AsyncClient]:
    """HTTP client over the real app, with storage swapped for the in-memory repository."""
    app = create_app(settings)
    app.dependency_overrides[get_project_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
```

`dependency_overrides` is why the routes depend on `get_project_service`: the test swaps one
function and the whole storage layer changes, with no edit to application code.
`ASGITransport` does not run the lifespan, so no database engine is created here.

`tests/api/test_projects.py`:

```python
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


async def test_delete_project_returns_204(client: AsyncClient) -> None:
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
```

`tests/integration/conftest.py`:

```python
"""Postgres fixtures: one schema per test session, one rolled-back transaction per test."""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import Settings
from app.models import Base


@pytest_asyncio.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()
```

The outer transaction is never committed: whatever a test writes disappears at rollback, so tests
cannot see each other's rows and need no cleanup code.

`tests/integration/test_project_repository.py`:

```python
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProjectNameConflictError
from app.repositories.project import SqlAlchemyProjectRepository
from app.schemas.project import ProjectCreate

pytestmark = pytest.mark.integration


def new_project(name: str = "BRCA cohort") -> ProjectCreate:
    return ProjectCreate(name=name, lead_scientist="Rosalind Franklin")


@pytest.fixture
def repository(session: AsyncSession) -> SqlAlchemyProjectRepository:
    return SqlAlchemyProjectRepository(session)


async def test_add_sets_server_defaults(repository: SqlAlchemyProjectRepository) -> None:
    project = await repository.add(new_project())

    assert project.project_id is not None
    assert project.created_at is not None
    assert project.completed_at is None


async def test_unique_constraint_maps_to_domain_error(
    repository: SqlAlchemyProjectRepository,
) -> None:
    await repository.add(new_project())

    with pytest.raises(ProjectNameConflictError):
        await repository.add(new_project())


async def test_list_all_returns_added_projects(repository: SqlAlchemyProjectRepository) -> None:
    first = await repository.add(new_project("first"))
    second = await repository.add(new_project("second"))

    assert {project.project_id for project in await repository.list_all()} == {
        first.project_id,
        second.project_id,
    }


async def test_get_and_delete(repository: SqlAlchemyProjectRepository) -> None:
    project = await repository.add(new_project())
    assert await repository.get(project.project_id) is project

    await repository.delete(project)

    assert await repository.get(project.project_id) is None


async def test_get_unknown_id_returns_none(repository: SqlAlchemyProjectRepository) -> None:
    assert await repository.get(uuid4()) is None
```

`tests/integration/test_projects_e2e.py`:

```python
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
```

This one test really commits, so it uses a unique name, deletes what it created and only checks for
its own project;
that keeps it independent of the rolled-back repository tests. The `engine` fixture is requested only to make
sure the schema exists.

Run:

```bash
poetry run pytest -m "not integration"     # unit + API, no Docker needed
docker compose up -d test_db
poetry run pytest --cov                    # everything, fails below 80% line coverage
```

Expected: 39 passed, total coverage around 98% (around 83% without the integration tests).

## Step 11. pre-commit hooks

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.17.5  # keep equal to the ruff version in poetry.lock
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format
```

```bash
poetry run pre-commit install            # installs the git hook in .git/hooks/pre-commit
poetry run pre-commit run --all-files    # run once over everything
```

On the first run `end-of-file-fixer` fixes `alembic/README` (the template has no final newline).
A hook that modifies files fails the commit on purpose: review the change, `git add` it, commit again.

## Step 12. CI with GitHub Actions

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

permissions:
  contents: read

env:
  POETRY_VERSION: "2.4.3"
  PYTHON_VERSION: "3.15"

jobs:
  lint:
    name: Lint and format
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - run: pipx install "poetry==$POETRY_VERSION"
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: poetry
      - run: poetry install --no-interaction
      # Each step runs one hook from .pre-commit-config.yaml, so CI and local checks never drift.
      - name: Lint (ruff check)
        run: poetry run pre-commit run ruff-check --all-files --show-diff-on-failure
      - name: Format (ruff format)
        run: poetry run pre-commit run ruff-format --all-files --show-diff-on-failure
      - name: Whitespace and end of file
        run: |
          poetry run pre-commit run trailing-whitespace --all-files --show-diff-on-failure
          poetry run pre-commit run end-of-file-fixer --all-files --show-diff-on-failure
      - name: Type check (mypy)
        run: poetry run mypy app tests

  test:
    name: Tests
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: app
          POSTGRES_PASSWORD: app
          POSTGRES_DB: gva_test
        ports:
          - 5433:5432
        options: >-
          --health-cmd "pg_isready -U app -d gva_test"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 5
    env:
      # Throwaway CI database; not a secret.
      DATABASE_URL: postgresql+asyncpg://app:app@localhost:5433/gva_test
      TEST_DATABASE_URL: postgresql+asyncpg://app:app@localhost:5433/gva_test
    steps:
      - uses: actions/checkout@v7
      - run: pipx install "poetry==$POETRY_VERSION"
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: poetry
      - run: poetry install --no-interaction
      - name: Migrations apply and roll back cleanly
        run: |
          poetry run alembic upgrade head
          poetry run alembic check
          poetry run alembic downgrade base
      - name: Tests with coverage gate
        run: poetry run pytest --cov --cov-report=term --cov-report=xml
      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: coverage
          path: coverage.xml
```

- Runs on every push (any branch) and every pull request; the two jobs run in parallel.
- Pipeline stages, each a separate named step so a failure shows exactly which one broke:
  lint (ruff check), format (ruff format), whitespace and end of file, type check (mypy),
  migrations, tests with coverage.
- The lint and format steps run single hooks from `.pre-commit-config.yaml`, so CI and your
  machine use the same tool versions and settings and cannot drift.
- Poetry is installed before `setup-python`, which then caches Poetry's downloads keyed on
  `poetry.lock`.
- The Postgres service container plays the role of `test_db`. The migration step proves upgrade,
  model/DB parity (`alembic check`) and downgrade before any test runs.
- `permissions: contents: read` gives the workflow token the minimum it needs.

In GitHub: Settings, Branches, add a rule for `main` requiring both jobs to pass before merging.

## Step 13. README.md

Write it for someone who has never seen the project. Suggested content:

````markdown
# Genomic Variant Analysis Platform

REST API to upload VCF files, filter and annotate genomic variants and retrieve summaries.
Week 1 scope: projects. Architecture: [ARCHITECTURE.md](ARCHITECTURE.md).

## Requirements
Python 3.15, Poetry 2.x, Docker with Compose v2.

## Run everything in Docker
```bash
docker compose up --build
```
API: http://127.0.0.1:8000, interactive docs: http://127.0.0.1:8000/docs

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
poetry run pytest --cov              # 80% coverage gate
poetry run pytest -m "not integration"   # fast, no database
```

## Migrations
```bash
poetry run alembic revision --autogenerate -m "describe the change"   # review the file!
poetry run alembic upgrade head
poetry run alembic downgrade -1
```

## API
| Method | Path | Success | Errors |
|---|---|---|---|
| POST | /api/v1/projects/ | 201 | 409, 422 |
| GET | /api/v1/projects/ | 200 | |
| DELETE | /api/v1/projects/{project_id}/ | 204 | 404, 422 |
| GET | /health | 200 | |

## Quality checks
`poetry run pre-commit run --all-files` (ruff lint + format, whitespace),
`poetry run mypy app tests`. CI runs the same checks plus tests on every push and pull request.
````

## Final verification

```bash
poetry install
docker compose up -d db test_db
poetry run alembic upgrade head && poetry run alembic check
poetry run pytest --cov
poetry run pre-commit run --all-files
poetry run mypy app tests
docker compose up --build -d --wait api
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/v1/projects/ \
  -H 'content-type: application/json' -d '{"name": "smoke", "lead_scientist": "Smoke Test"}'  # 201
docker compose down
git push                                                          # watch CI go green
```

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `ValidationError: database_url Field required` | No `.env` and no `DATABASE_URL` | `cp .env.example .env` |
| `InvalidCatalogNameError` or connection refused | Database container not running, or wrong port | `docker compose up -d db` (5434) or `test_db` (5433) |
| `NoSuchModuleError: postgresql.asyncpg` or a sync driver error | URL without `+asyncpg` | Use `postgresql+asyncpg://...` |
| Autogenerate creates an empty migration | Model not imported in `app/models/__init__.py` | Add the import, regenerate |
| "attached to a different loop" in tests | Per-test event loops | Keep the `asyncio_default_*_loop_scope = "session"` settings |
| 307 Temporary Redirect | Path without trailing slash | Call `/api/v1/projects/` |
| `MissingGreenlet` | Lazy-loading an attribute outside `await` | Keep `expire_on_commit=False`; load what you need inside the repository |
| pre-commit fails, then passes on the second commit | A hook fixed files | Review, `git add`, commit again |
