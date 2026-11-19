"""Run the project quality gate with token-lean output.

Steps, cheapest first: dashes, ruff check, ruff format, mypy, pytest with coverage (mirrors CI).
Stops at the first failing step and prints about 40 lines at most; the full output goes to
.claude/logs/check.log.

Usage: poetry run python scripts/check.py [extra pytest args, e.g. --lf or tests/unit]
Extra pytest args mean a partial run, so the coverage gate is skipped.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / ".claude" / "logs" / "check.log"
MAX_LINES = 40
FRAME = re.compile(r"^(\S.*?):\d+: in ")
SUMMARY = re.compile(r"\d+ (failed|passed|errors?)\b")
TOTAL = re.compile(r"^TOTAL\s.*?(\d+(?:\.\d+)?%)\s*$")
DASHES = re.compile("[\N{EN DASH}\N{EM DASH}]")
DASH_SUFFIXES = {".py", ".md", ".toml", ".json", ".txt", ".cfg", ".ini", ".yml", ".yaml", ".mako"}
DASH_NAMES = {"Dockerfile", ".dockerignore", ".gitignore", ".env.example"}
DB_DOWN = ("ConnectionRefusedError", "Connect call failed")


def project_files() -> list[Path]:
    """Tracked and untracked files, minus anything .gitignore excludes."""
    out = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / name for name in out.splitlines()]


def dash_check() -> tuple[int, str]:
    """House rule: no em dash (U+2014) or en dash (U+2013) in code, comments or docs."""
    hits: list[str] = []
    for path in project_files():
        if path.suffix not in DASH_SUFFIXES and path.name not in DASH_NAMES:
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for no, line in enumerate(text.splitlines(), 1):
            if DASHES.search(line):
                hits.append(f"{rel}:{no}: {line.strip()[:100]}")
    if not hits:
        return 0, "no em/en dashes"
    note = f"Found {len(hits)} em/en dash(es); reword with a colon, comma, period or parentheses."
    return 1, "\n".join([*hits, note])


def steps(pytest_args: list[str]) -> list[tuple[str, list[str]]]:
    py = sys.executable
    coverage = [] if pytest_args else ["--cov"]
    return [
        ("ruff", [py, "-m", "ruff", "check", "--output-format", "concise", "."]),
        ("format", [py, "-m", "ruff", "format", "--check", "."]),
        ("mypy", [py, "-m", "mypy", "app", "tests"]),
        ("pytest", [py, "-m", "pytest", "-x", "--tb=short", "-rfE", *coverage, *pytest_args]),
    ]


def last_line(output: str) -> str:
    lines = [line.strip("= ") for line in output.splitlines() if line.strip()]
    return next(
        (line for line in reversed(lines) if SUMMARY.search(line)), lines[-1] if lines else ""
    )


def coverage_total(output: str) -> str | None:
    return next((m.group(1) for line in output.splitlines() if (m := TOTAL.match(line))), None)


def is_project(path: str) -> bool:
    return (
        "site-packages" not in path and not Path(path).is_absolute() and not path.startswith("..")
    )


def drop_library_frames(lines: list[str]) -> list[str]:
    """Remove traceback frames (header + indented source) outside the project."""
    kept: list[str] = []
    hidden = 0
    skipping = False
    for line in lines:
        match = FRAME.match(line)
        if match:
            skipping = not is_project(match.group(1))
            hidden += skipping
        elif skipping and not line.startswith(" "):
            skipping = False
        if not skipping:
            kept.append(line)
    if hidden:
        kept.append(f"({hidden} library frames hidden)")
    return kept


def pytest_excerpt(lines: list[str]) -> list[str]:
    """First failing test, or the coverage table when only the coverage gate failed."""
    start = next((i for i, line in enumerate(lines) if line.startswith("____")), None)
    if start is not None:
        end = next(
            (j for j in range(start + 1, len(lines)) if lines[j].startswith(("____", "===="))),
            len(lines),
        )
        summary = [line for line in lines if line.startswith(("FAILED", "ERROR"))]
        return [*drop_library_frames(lines[start:end]), *summary]
    table = next((i for i, line in enumerate(lines) if line.startswith("Name ")), None)
    return lines[table:] if table is not None else lines


def excerpt(name: str, output: str) -> list[str]:
    lines = output.splitlines()
    if name == "pytest":
        lines = pytest_excerpt(lines)
        if any(marker in output for marker in DB_DOWN):
            lines.append("hint: Postgres refused; docker compose up -d test_db, then rerun")
    if len(lines) > MAX_LINES:
        hidden = len(lines) - MAX_LINES
        lines = [*lines[:MAX_LINES], f"... (+{hidden} lines, see {LOG.relative_to(ROOT)})"]
    return lines


def ok_status(name: str, output: str) -> str:
    if name != "pytest":
        return "ok"
    total = coverage_total(output)
    detail = last_line(output) + (f", coverage {total}" if total else ", coverage skipped")
    return f"ok ({detail})"


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    report: list[str] = []
    with LOG.open("w", encoding="utf-8") as log:
        code, output = dash_check()
        log.write(f"===== dashes\n{output}\n")
        if code != 0:
            print("\n".join(["dashes: FAIL", *excerpt("dashes", output)]))
            return 1
        report.append("dashes: ok")
        for name, cmd in steps(sys.argv[1:]):
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
            output = proc.stdout + proc.stderr
            log.write(f"===== {name}: {' '.join(cmd[1:])}\n{output}\n")
            if proc.returncode != 0:
                report.append(f"{name}: FAIL ({last_line(output)})")
                report.extend(excerpt(name, output))
                report.append(f"full log: {LOG.relative_to(ROOT).as_posix()}")
                print("\n".join(report))
                return 1
            report.append(f"{name}: {ok_status(name, output)}")
    print("check: pass · " + " · ".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
