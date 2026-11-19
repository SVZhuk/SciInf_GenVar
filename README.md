# Genomic Variant Analysis Platform

Training project: a REST API (FastAPI, Pydantic v2, async SQLAlchemy, Postgres) to upload VCF
files, filter and annotate genomic variants and retrieve summaries. Each week adds features;
week 1 builds the project foundation and the Projects API.

## Branches

Pick the branch that matches how much help you want. Each one builds on the previous.

| Branch | Contains | Use it to |
|---|---|---|
| `main` | Task brief, architecture template, Claude Code configuration | Start from scratch and design the solution yourself |
| `week_1_setup` | `main` plus detailed guidance: concrete layer layout, filled-in architecture, extra Claude Code skill | Build week 1 with a clear target structure |
| `week_1_implementation` | `week_1_setup` plus the full working week 1 solution and a step-by-step walkthrough | Compare your work or study a reference implementation |

## Start here

1. Read [TASK.md](TASK.md): the week 1 brief, milestones and grading rubric.
2. Read [ARCHITECTURE.md](ARCHITECTURE.md) and fill it in as you design.
3. [CLAUDE.md](CLAUDE.md) holds the project rules; Claude Code agents, skills and hooks live in
   `.claude/`.

## Requirements

Python 3.15, Poetry 2.x, Docker with Compose v2, git.
