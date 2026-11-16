"""PreToolUse hook: keep credentials out of the agent's context and out of written files.

Blocks reading, grepping or shelling into credential files (.env, tfvars, tfstate, keys, ~/.aws),
commands that dump secrets (env, aws configure get, terraform output -json, ...) and writes whose
content contains a secret. Reads the hook payload on stdin; exit 2 sends stderr back to the agent.
Messages never echo the matched value.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shlex
import sys
from typing import Any

SPLIT = re.compile(r"&&|\|\||;|\||\n")
ASSIGNMENT = re.compile(r"^\w+=")
SAFE_SUFFIXES = (".example", ".sample", ".template", ".dist", ".pub")
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".tfvars", ".tfvars.json")
SECRET_NAMES = {".env", ".envrc", ".netrc", ".pgpass", ".git-credentials", "tfplan"}
SECRET_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")
HOME_SECRETS = {
    ".aws": {"credentials", "config"},
    ".docker": {"config.json"},
    ".kube": {"config"},
}
GLOB_PROBES = (
    ".env",
    ".env.local",
    "terraform.tfvars",
    "terraform.tfstate",
    "terraform.tfstate.backup",
    "tfplan",
    "server.pem",
    "server.key",
    "id_rsa",
    "credentials",
)
FILE_FLAGS = {"--env-file", "-var-file", "--var-file"}
SECRET_VAR = re.compile(
    r"\$\{?(env:)?\w*(SECRET|TOKEN|PASSWORD|PASSWD|API_KEY|ACCESS_KEY|PRIVATE_KEY|CREDENTIAL)\w*",
    re.IGNORECASE,
)
STRONG = {
    "AWS access key id": re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    "AWS secret access key": re.compile(
        r"aws_secret_access_key\s*[=:]\s*[\"']?[A-Za-z0-9/+]{40}", re.IGNORECASE
    ),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b"),
    "Slack token": re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
}
GENERIC = re.compile(
    r"(password|passwd|secret|token|api_?key|access_?key)[\"']?\s*[=:]\s*[\"']([^\"'\s]{8,})[\"']",
    re.IGNORECASE,
)
PLACEHOLDER = re.compile(
    r"[$<{*]|example|changeme|placeholder|dummy|xxx|your|fake|redacted|replace", re.IGNORECASE
)
NOTE = (
    "Keep credentials out of the conversation and the repo. Use the .example file or ask the user."
)


def is_secret_path(raw: str) -> bool:
    path = raw.strip("\"'").replace("\\", "/").lstrip("@<>")
    if not path:
        return False
    parts = [part for part in path.lower().split("/") if part]
    if not parts:
        return False
    name = parts[-1]
    if name.endswith(SAFE_SUFFIXES):
        return False
    if name in SECRET_NAMES or name.startswith(".env.") or ".tfstate" in name:
        return True
    if (
        name.endswith(SECRET_SUFFIXES)
        or name.endswith(".tfplan")
        or name.startswith(SECRET_PREFIXES)
    ):
        return True
    if ".ssh" in parts[:-1]:
        return True
    return any(folder in parts[:-1] and name in names for folder, names in HOME_SECRETS.items())


def expand_braces(pattern: str) -> list[str]:
    match = re.match(r"(.*?)\{([^}]*)\}(.*)", pattern)
    if not match:
        return [pattern]
    head, body, tail = match.groups()
    return [alt for option in body.split(",") for alt in expand_braces(head + option + tail)]


def is_secret_glob(pattern: str) -> bool:
    for alt in expand_braces(pattern):
        name = alt.replace("\\", "/").rsplit("/", 1)[-1]
        if not name.strip("*?.") or name.endswith(SAFE_SUFFIXES):
            continue
        if is_secret_path(alt) or any(fnmatch.fnmatch(probe, name) for probe in GLOB_PROBES):
            return True
    return False


def tokens_of(segment: str) -> list[str]:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    return [token for token in tokens if not ASSIGNMENT.match(token)]


def path_candidates(token: str) -> list[str]:
    return [token, *re.split(r"[=:]", token)[1:]]


def dangerous_command(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    head = tokens[0].rsplit("/", 1)[-1].lower()
    args = [token.lower() for token in tokens[1:]]
    sub = " ".join(args[:2])
    if head in {"env", "printenv"} and all(arg.startswith("-") for arg in args):
        return "environment dump"
    if head in {"set", "export", "declare"} and args in ([], ["-p"], ["-x"]):
        return "environment dump"
    if any(arg.rstrip("/\\") == "env:" for arg in args):
        return "environment dump"
    if head == "aws" and (
        sub in {"configure get", "configure export-credentials", "iam create-access-key"}
        or sub.startswith(
            ("sts get-session-token", "sts assume-role", "secretsmanager get-secret-value")
        )
        or (sub.startswith("ssm get-parameter") and "--with-decryption" in args)
    ):
        return f"aws {sub}"
    if head in {"terraform", "tofu"}:
        if sub == "state pull":
            return "terraform state pull"
        if args[:1] == ["show"] and "-json" in args:
            return "terraform show -json"
        if args[:1] == ["output"] and ({"-json", "-raw"} & set(args)):
            return "terraform output -json/-raw"
    if (head == "docker" and sub == "compose config") or (
        head == "docker-compose" and args[:1] == ["config"]
    ):
        return "docker compose config"
    return None


def check_shell(command: str) -> str | None:
    for rule, pattern in STRONG.items():
        if pattern.search(command):
            return f"{rule} in command"
    if SECRET_VAR.search(command):
        return "secret environment variable referenced in command"
    segments = SPLIT.split(command.replace("\\", "/"))
    for segment in segments:
        tokens = tokens_of(segment)
        reason = dangerous_command(tokens)
        if reason:
            return reason
        if len(segments) == 1 and tokens[:2] in (["git", "ls-files"], ["git", "check-ignore"]):
            continue
        for index, token in enumerate(tokens):
            if index and tokens[index - 1] in FILE_FLAGS:
                continue
            if token.split("=", 1)[0] in FILE_FLAGS:
                continue
            if any(is_secret_path(candidate) for candidate in path_candidates(token)):
                return f"credential file '{token.rsplit('/', 1)[-1]}' in command"
    return None


def written_texts(tool_input: dict[str, Any]) -> list[str]:
    texts = [str(tool_input.get(key, "")) for key in ("content", "new_string", "new_source")]
    texts += [str(edit.get("new_string", "")) for edit in tool_input.get("edits", []) or []]
    return [text for text in texts if text]


def check_content(texts: list[str]) -> str | None:
    for text in texts:
        for rule, pattern in STRONG.items():
            if pattern.search(text):
                return rule
        for match in GENERIC.finditer(text):
            if not PLACEHOLDER.search(match.group(2)):
                return f"hardcoded {match.group(1).lower()}"
    return None


def check(tool: str, tool_input: dict[str, Any]) -> str | None:
    if tool in {"Bash", "PowerShell"}:
        return check_shell(str(tool_input.get("command", "")))
    for key in ("file_path", "notebook_path", "path"):
        target = str(tool_input.get(key, "") or "")
        if target and is_secret_path(target):
            return f"credential file '{target.replace(chr(92), '/').rsplit('/', 1)[-1]}'"
    if tool == "Grep" and is_secret_glob(str(tool_input.get("glob", "") or "")):
        return "grep over credential files"
    rule = check_content(written_texts(tool_input))
    if rule:
        target = str(tool_input.get("file_path", "") or tool_input.get("notebook_path", ""))
        return f"{rule} in content written to '{target.replace(chr(92), '/').rsplit('/', 1)[-1]}'"
    return None


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    reason = check(str(payload.get("tool_name", "")), payload.get("tool_input", {}) or {})
    if reason:
        sys.stderr.write(f"Blocked by secret_guard: {reason}.\n{NOTE}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
