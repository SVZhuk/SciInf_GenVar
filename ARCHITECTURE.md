# Architecture: Genomic Variant Analysis Platform

Living document: update it in the same pull request as the change it describes.
Status markers: **[done]** implemented, **[planned]** designed but not built yet.

## 1. Overview

A REST API for genomic variant analysis. Users create projects, upload VCF files, the service parses
variants into Postgres, applies annotation files, and returns filtered variants and summaries.

```mermaid
flowchart LR
    U[Client / curl / UI] -->|HTTPS| ALB[AWS ALB]
    ALB --> ECS["ECS Fargate<br/>FastAPI container"]
    ECS -->|asyncpg| RDS[(RDS Postgres)]
    ECS -->|boto3| S3[(S3: raw VCF and<br/>annotation files)]
    GH[GitHub Actions] -->|image| ECR[ECR]
    ECR --> ECS
```

| Component | Role | Status |
|---|---|---|
| FastAPI app in Docker | REST API | **[done]** week 1 |
| Postgres (local Docker) | Relational storage | **[done]** week 1 |
| GitHub Actions: lint, format, type check, tests | Quality gate on every push and PR | **[done]** week 1 |
| AWS S3 | Raw uploaded files, referenced by `s3_key` | **[planned]** |
| AWS RDS Postgres | Managed production database | **[planned]** |
| ECR + ECS Fargate + ALB | Image registry, serverless containers, load balancer | **[planned]** |
| GitHub Actions: build, push, deploy | Continuous delivery | **[planned]** |

## 2. Tech stack

| Concern | Tool | Why |
|---|---|---|
| Language | Python 3.15 | Latest stable release; one version locally, in Docker and in CI |
| Web framework | FastAPI | Type hints drive validation, routing and OpenAPI docs (`/docs`) |
| Validation / DTOs | Pydantic v2, pydantic-settings | Request/response contracts; typed config from env |
| ORM | SQLAlchemy 2.0 async + asyncpg | Typed declarative models, non-blocking IO |
| Migrations | Alembic (async template) | Versioned, reviewable schema changes |
| Server | Uvicorn | ASGI server, app built by factory (`--factory`) |
| Dependencies | Poetry (`pyproject.toml`, `poetry.lock`, in-project `.venv`) | Reproducible installs |
| Tests | pytest, pytest-asyncio, pytest-cov, httpx | Async tests, in-process HTTP, 80% coverage gate |
| Quality | ruff (lint + format), mypy strict, pyright, pre-commit | Same checks locally and in CI |
| Containers | Docker multi-stage, Compose | Non-root runtime image; one-command local stack |
| CI/CD | GitHub Actions | Runs on every push and pull request |

## 3. Layers

```mermaid
flowchart TB
    R["api/v1/routes/<br/>HTTP handlers"] --> S["services/<br/>business rules"]
    R -. validates with .-> SC["schemas/<br/>Pydantic DTOs"]
    D["api/deps.py<br/>DI wiring"] -. builds .-> S
    S --> RP["repositories/<br/>storage access"]
    S -. planned .-> ST["storage/s3.py<br/>file storage"]
    RP --> M["models/<br/>SQLAlchemy tables"]
    M --> PG[(Postgres)]
    ST -.-> S3[(S3)]
```

Dependencies point one way: routes to services to repositories. Nothing imports "upwards".

| Package | Responsibility | Must not |
|---|---|---|
| `app/api/v1/routes/` | Map HTTP to service calls; domain errors to status codes | import `repositories/` or `db/` |
| `app/api/v1/router.py` | Mount resource routers under `/api/v1` | contain handlers |
| `app/api/deps.py` | Build services and their dependencies (the "beans") | contain logic |
| `app/services/` | Business rules and orchestration of one use case | import FastAPI |
| `app/repositories/` | Only code that reads/writes storage; DB errors to domain errors | import FastAPI, hold business rules |
| `app/schemas/` | API contract (what clients send and receive) | know about storage |
| `app/models/` | Table definitions | open sessions, run queries |
| `app/db/` | Engine lifecycle, one session per request | contain business rules |
| `app/core/` | Settings, logging, domain exceptions | import other `app` layers |
| `app/main.py` | Assemble the app (factory) | contain endpoint logic |

### Design patterns

| Pattern | Where | What it buys |
|---|---|---|
| Application Factory | `create_app(settings)` in `app/main.py` | Fresh, explicitly configured app per test; no import-time side effects |
| Layered architecture | routes, services, repositories | Each change touches one layer |
| Repository | `ProjectRepository` Protocol, `SqlAlchemyProjectRepository`, `InMemoryProjectRepository` | Storage swappable without touching services or routes |
| Service Layer | `ProjectService` | One home for business rules and multi-step use cases |
| Dependency Injection | `Annotated[..., Depends(...)]` in `app/api/deps.py` | Routes receive ready services; tests override one provider |
| Unit of Work | `get_session`: `session.begin()` per request | One transaction per request; commit or roll back as a whole |
| DTO | `ProjectCreate`, `ProjectRead` | Clients cannot set server-owned fields (`project_id`, `created_at`, `completed_at`) |

SOLID in practice:
- Single responsibility: one job per layer (table above).
- Open/closed: a new resource adds new files (schema, model, repository, service, route) and one
  `include_router` line; existing resources do not change.
- Liskov substitution: both repositories satisfy the same Protocol; the service cannot tell them apart.
- Interface segregation: the repository Protocol lists only the operations the service uses.
- Dependency inversion: `ProjectService` depends on the `ProjectRepository` abstraction; only
  `api/deps.py` chooses the concrete class.

## 4. Directory layout

```text
app/
  main.py                    factory, lifespan, /health
  core/                      config.py, logging.py, exceptions.py
  db/                        base.py (Base + naming convention), session.py (engine, get_session)
  models/                    one module per table; __init__.py imports all of them
  schemas/                   one module per resource
  repositories/              one module per aggregate
  services/                  one module per resource / use case
  storage/                   [planned] S3 client wrapper
  parsers/                   [planned] VCF and annotation file parsers (pure functions)
  api/deps.py
  api/v1/router.py
  api/v1/routes/             one module per resource
alembic/versions/            one revision per schema change
tests/unit/ tests/api/ tests/integration/
docs/                        week-NN-implementation.md guides
```

## 5. Request lifecycle

`POST /api/v1/projects/`:

```mermaid
sequenceDiagram
    participant C as Client
    participant MW as log_requests
    participant F as FastAPI
    participant R as create_project route
    participant S as ProjectService
    participant RP as SqlAlchemyProjectRepository
    participant DB as Postgres
    C->>MW: POST /api/v1/projects/ {name, lead_scientist, description}
    MW->>F: call_next
    F->>F: validate body as ProjectCreate
    alt invalid body
        F-->>C: 422
    end
    F->>F: get_session opens session + transaction
    F->>R: payload, ProjectServiceDep
    R->>S: create_project(payload)
    S->>RP: add(payload)
    RP->>DB: INSERT ... RETURNING created_at
    alt name exists (uq_projects_name)
        DB-->>RP: IntegrityError
        RP-->>S: ProjectNameConflictError
        S-->>R: re-raise (WARNING logged)
        R-->>C: 409
    end
    RP-->>S: ProjectModel
    S-->>R: ProjectModel (INFO "Project created project_id=...")
    R->>R: ProjectRead.model_validate
    F->>DB: COMMIT (session scope ends before the response)
    MW-->>C: 201 + JSON (INFO "POST ... -> 201 (x ms)")
```

1. Validation runs before any of our code; bad input never reaches the service.
2. One session and one transaction per request; any exception rolls everything back.
3. Domain errors are plain Python exceptions; only routes translate them to HTTP.
4. Output always goes through a response schema, never a raw ORM object.

## 6. Data model

Target relational schema. Week 1 implements `projects` only.

```mermaid
erDiagram
    projects ||--o{ vcf_files : contains
    projects ||--o{ annotation_files : contains
    vcf_files ||--o{ variants : "parsed into"
    variants ||--o{ annotations : "annotated by"
    annotation_files ||--o{ annotations : provides

    projects {
        uuid project_id PK
        varchar(100) name UK
        varchar(100) lead_scientist
        text description "nullable"
        timestamptz created_at "default now()"
        timestamptz completed_at "nullable, NULL while running"
    }
    vcf_files {
        uuid vcf_file_id PK
        uuid project_id FK "on delete cascade"
        varchar(255) filename
        varchar(1024) s3_key UK
        varchar(20) status "uploaded, parsing, parsed, failed"
        int variant_count "nullable"
        timestamptz uploaded_at "default now()"
    }
    variants {
        bigint variant_id PK
        uuid vcf_file_id FK "on delete cascade"
        varchar(50) chrom
        bigint pos "1-based, as in VCF"
        varchar(100) vcf_id "VCF ID column, e.g. rs123, nullable"
        text ref
        text alt
        float qual "nullable"
        varchar(100) filter "nullable"
        jsonb info
    }
    annotation_files {
        uuid annotation_file_id PK
        uuid project_id FK "on delete cascade"
        varchar(255) filename
        varchar(1024) s3_key UK
        varchar(50) source "e.g. VEP, ClinVar"
        timestamptz uploaded_at "default now()"
    }
    annotations {
        bigint annotation_id PK
        bigint variant_id FK "on delete cascade"
        uuid annotation_file_id FK "on delete cascade"
        varchar(50) gene "nullable"
        varchar(100) consequence "nullable"
        varchar(50) clinical_significance "nullable"
        jsonb extra
    }
```

| Table | Status | Constraints and indexes |
|---|---|---|
| `projects` | **[done]** | `pk_projects`, `uq_projects_name`; index on `created_at` once listing is paginated |
| `vcf_files` | **[planned]** | FK to projects (cascade), unique `s3_key`, index on `project_id` |
| `variants` | **[planned]** | FK to vcf_files (cascade); unique (`vcf_file_id`, `chrom`, `pos`, `ref`, `alt`); index (`chrom`, `pos`) for region queries |
| `annotation_files` | **[planned]** | FK to projects (cascade), unique `s3_key` |
| `annotations` | **[planned]** | FKs to variants and annotation_files (cascade); unique (`variant_id`, `annotation_file_id`); index on `gene` |

Design decisions:
- File bytes live in S3; the database stores only metadata and `s3_key`. Rows stay small and
  backups stay cheap.
- `variants.variant_id` is `bigint` (identity), not UUID: a single VCF can hold millions of rows, and a
  sequential 8-byte key keeps the index compact. Resources clients address directly (projects,
  files) use UUIDs, which do not leak counts and can be generated anywhere.
- Multi-allelic VCF lines are split into one row per ALT allele, so (`chrom`, `pos`, `ref`, `alt`)
  identifies a variant within a file.
- `info` and `extra` are `jsonb`: VCF INFO fields and annotation columns differ by caller and tool.
  Fields that become filters (for example `gene`, `consequence`) get their own columns.
- Status columns are `VARCHAR` validated by a Python enum, not native Postgres enums: adding a
  value is then an ordinary migration.
- Deleting a project cascades to its files, variants and annotations (`ON DELETE CASCADE`). The
  matching S3 objects must be deleted by the service.
- Column naming: snake_case; plural table names; primary key `<entity>_id` (`project_id`,
  `vcf_file_id`, ...), so a foreign key column has the same name as the key it references; no table
  prefix on other columns (`projects.name`, not `project_name`); timestamps end in `_at` and are
  `timestamptz`; booleans start with `is_`/`has_`. Rationale: guide step 5, "Naming conventions".
- All constraint names come from the naming convention in `app/db/base.py`.

## 7. REST API

| Method | Path | Success | Errors | Status |
|---|---|---|---|---|
| GET | `/health` | 200 `{"status": "ok"}` | | **[done]** |
| POST | `/api/v1/projects/` | 201 `ProjectRead` | 409 name exists, 422 | **[done]** |
| GET | `/api/v1/projects/` | 200 `list[ProjectRead]`, oldest first | | **[done]** |
| DELETE | `/api/v1/projects/{project_id}/` | 204 | 404, 422 bad UUID | **[done]** |
| GET | `/api/v1/projects/{project_id}/` | 200 | 404 | **[planned]** |
| POST | `/api/v1/projects/{project_id}/complete/` | 200, sets `completed_at` | 404, 409 already completed | **[planned]** |
| POST | `/api/v1/projects/{project_id}/vcf-files/` | 202, multipart upload | 404, 413, 422 | **[planned]** |
| GET | `/api/v1/projects/{project_id}/vcf-files/` | 200 | 404 | **[planned]** |
| GET | `/api/v1/vcf-files/{vcf_file_id}/variants/?chrom=&start=&end=&gene=&limit=&offset=` | 200 page | 404, 422 | **[planned]** |
| POST | `/api/v1/projects/{project_id}/annotation-files/` | 202 | 404, 422 | **[planned]** |
| GET | `/api/v1/projects/{project_id}/summary/` | 200 counts by chrom, consequence, significance | 404 | **[planned]** |

Conventions: plural nouns, trailing slash on every path (as specified), `/api/v1` version prefix,
201 for create, 204 for delete, 404 for unknown ids, 409 for conflicts, 422 left to Pydantic.
Lists will get `limit`/`offset` pagination once they can grow large (variants first).

## 8. Cross-cutting concerns

### Configuration
Environment variables, read once by `Settings` (`app/core/config.py`); `.env` locally, ECS task
definition plus Secrets Manager in AWS.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | yes | | `postgresql+asyncpg://...`; held as `SecretStr` |
| `LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `TEST_DATABASE_URL` | tests only | `...localhost:5433/gva_test` | Integration tests |

### Logging
- stdlib `logging`, configured once in the lifespan (`configure_logging`), output to stdout
  (collected by Docker and, later, CloudWatch).
- `log_requests` middleware: one line per request with method, path, status, duration; level INFO
  for 2xx/3xx, WARNING for 4xx, ERROR for 5xx.
- Services log state changes at INFO and rejected requests at WARNING; repositories log row-level
  detail at DEBUG.
- Never logged: request bodies, query strings, `DATABASE_URL`, credentials, VCF content.
- **[planned]** JSON log format and a request id for CloudWatch Logs Insights.

### Migrations
- Every schema change is an Alembic revision generated with `--autogenerate`, then reviewed by hand.
- Each revision must downgrade cleanly; CI runs `upgrade head`, `check`, `downgrade base`.
- In Docker Compose (and later ECS), a one-off `migrate` container runs `alembic upgrade head`
  before the API starts.

### Testing
| Layer | Scope | Storage |
|---|---|---|
| `tests/unit/` | schemas, services, in-memory repository | in memory |
| `tests/api/` | HTTP contract through the real app | in memory (dependency override) |
| `tests/integration/` | SQL repository, full stack with lifespan | Postgres `test_db`, rolled back per test |

Line coverage gate: 80% (`[tool.coverage.report] fail_under`), currently about 98%.
Tests follow FIRST and Arrange, Act, Assert. Every endpoint has a happy-path test plus one test per
documented error status.

### CI/CD
| Stage | Tool | Status |
|---|---|---|
| Lint + format + whitespace/EOF | pre-commit (ruff, pre-commit-hooks) | **[done]** |
| Type check | mypy strict | **[done]** |
| Migrations up/check/down | Alembic against a Postgres service container | **[done]** |
| Tests + coverage gate + coverage artifact | pytest-cov | **[done]** |
| Build and push image | Docker, ECR | **[planned]** |
| Deploy | ECS service update, migrations as one-off task | **[planned]** |

## 9. Decision log

| # | Decision | Reason |
|---|---|---|
| 1 | Poetry for dependencies, in-project `.venv` | Course requirement; lock file for reproducible installs |
| 2 | Routes, services, repositories as separate layers | Business logic for VCF/S3 workflows needs a home that is neither HTTP nor SQL |
| 3 | Repository as `Protocol` with an in-memory implementation | Fast, DB-free unit and API tests; storage can change without touching services |
| 4 | `/api/v1` prefix around the specified paths | Room for a breaking v2 without breaking v1 clients |
| 5 | UUID keys for client-facing resources, bigint for variants | Non-guessable public ids; compact index for millions of variant rows |
| 6 | Uniqueness enforced by DB constraints, mapped to 409 (`projects.name` now, `s3_key` later) | No race between "check" and "insert" |
| 7 | Settings injected into `create_app` | Tests never depend on `.env`; no import-time side effects |
| 8 | Python 3.15, the latest stable release | Same version locally, in Docker and in CI |

## 10. Changelog by week

### Week 1
Project skeleton, Poetry, Docker and Compose (db, test_db, migrate, api), settings, logging,
`projects` table (`project_id`, `name`, `lead_scientist`, `description`, `created_at`,
`completed_at`) and first migration, `POST`/`GET`/`DELETE` projects endpoints, unit/API/integration
tests (coverage about 98%), pre-commit, GitHub Actions CI.
