# Genomic Variant Analysis Platform

Training project: a REST API (FastAPI, Pydantic v2, async SQLAlchemy, Postgres) to upload VCF
files, filter and annotate genomic variants and retrieve summaries. Each week adds features;
week 1 builds the project foundation and the Projects API.

You are on `week_1_setup`: the task plus detailed guidance on the target structure.

## Branches

Pick the branch that matches how much help you want. Each one builds on the previous.

| Branch | Contains | Use it to |
|---|---|---|
| `main` | Task brief, architecture template, Claude Code configuration | Start from scratch and design the solution yourself |
| `week_1_setup` | `main` plus detailed guidance: concrete layer layout, filled-in architecture, extra Claude Code skill | Build week 1 with a clear target structure |
| `week_1_implementation` | `week_1_setup` plus the full working week 1 solution and a step-by-step walkthrough | Compare your work or study a reference implementation |

## Guidance on this branch

| File | What it gives you |
|---|---|
| [TASK.md](TASK.md) | Week 1 brief, milestones and grading rubric |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Filled-in architecture: layers, directory layout, request lifecycle, data model, REST API |
| [CLAUDE.md](CLAUDE.md) | Project rules: layer boundaries (`api/v1/routes/`, `services/`, `repositories/`), typing, logging, testing |
| `.claude/agents/` | `reviewer`, `code-improver`, `test-fixer`, `iac-guard` subagents |
| `.claude/skills/` | `add-endpoint` (schemas, repository, service, route, tests in order), `check`, `terraform-aws` |
| `.claude/hooks/` | Guards for Poetry usage, secrets and dashes, plus a stop hook that runs the check |

## Start here

1. Read TASK.md, then ARCHITECTURE.md sections 3 and 4 for the target layout.
2. Create the Poetry project and package skeleton that ARCHITECTURE.md describes.
3. Build the Projects API layer by layer; the `add-endpoint` skill lists the order.
4. The `check` skill and the stop hook run `scripts/check.py` (tests, coverage at least 80%, ruff,
   mypy). It is not on this branch yet: write your own or take it from `week_1_implementation`.

## Requirements

Python 3.15, Poetry 2.x, Docker with Compose v2, git.
