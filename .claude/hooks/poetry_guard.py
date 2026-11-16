"""PreToolUse hook: keep Bash commands on Poetry.

Blocks pip, uv, venv creation and bare python/pytest/ruff/mypy/uvicorn/alembic calls, including
ones hidden behind &&, ||, ; or a pipe. Reads the hook payload on stdin; exit 2 sends stderr back
to the agent.
"""

from __future__ import annotations

import json
import re
import shlex
import sys

SPLIT = re.compile(r"&&|\|\||;|\|")
ASSIGNMENT = re.compile(r"^\w+=")
BLOCKED = {
    "pip": "poetry add (deps) or poetry install",
    "pip3": "poetry add (deps) or poetry install",
    "uv": "poetry add (deps), poetry install or poetry run",
    "virtualenv": "poetry install (creates .venv from poetry.lock)",
    "python": "poetry run python",
    "python3": "poetry run python",
    "py": "poetry run python",
    "pytest": "poetry run pytest",
    "ruff": "poetry run ruff",
    "mypy": "poetry run mypy",
    "uvicorn": "poetry run uvicorn",
    "alembic": "poetry run alembic",
}


def first_token(segment: str) -> str:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return ""
    tokens = [token for token in tokens if not ASSIGNMENT.match(token)]
    return tokens[0].rsplit("/", 1)[-1] if tokens else ""


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    command = str(payload.get("tool_input", {}).get("command", ""))
    for segment in SPLIT.split(command):
        token = first_token(segment)
        if token in BLOCKED:
            sys.stderr.write(
                f"Blocked: '{token}' must go through Poetry. Use: {BLOCKED[token]}.\n"
                "This project manages dependencies with Poetry (pyproject.toml + poetry.lock).\n"
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
