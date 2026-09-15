"""Shared evidence helpers for the verification-in-the-loop tools.

The schema here is intentionally small. Tool-specific runners should emit
one normalized finding per checked property, then higher-level gates can
reconcile those findings against a Verification Plan.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
REPO = Path(__file__).resolve().parents[1]

VALID_STATUSES = {"pass", "fail", "error", "skipped", "unverified"}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_run_id(prefix: str = "run") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}"


def relpath(path: str | Path) -> str:
    p = Path(path)
    if not p.is_absolute():
        return p.as_posix()
    try:
        return p.relative_to(REPO).as_posix()
    except ValueError:
        return p.as_posix()


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())


def write_json(path: str | Path, value: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2) + "\n")


def command_version(command: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd or REPO,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception as exc:  # pragma: no cover - defensive wrapper
        return f"unavailable: {exc}"
    text = (result.stdout or result.stderr).strip()
    return text.splitlines()[0] if text else f"exit {result.returncode}"


def repo_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def new_document(
    *,
    run_id: str | None = None,
    tool: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "run_id": run_id or default_run_id(),
            "timestamp": utc_timestamp(),
            "repo": relpath(REPO),
            "commit": repo_commit(),
            "tool": tool,
            "metadata": metadata or {},
        },
        "findings": [],
    }


def make_finding(
    *,
    function: str,
    property_id: str,
    tool: str,
    evidence_level: str,
    status: str,
    kind: str,
    expected: Any = None,
    actual: Any = None,
    location: dict[str, Any] | None = None,
    assumptions: list[str] | None = None,
    artifacts: dict[str, str] | None = None,
    diagnostics: str | None = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid evidence status {status!r}")
    finding = {
        "function": function,
        "property_id": property_id,
        "tool": tool,
        "evidence_level": evidence_level,
        "kind": kind,
        "status": status,
        "expected": expected,
        "actual": actual,
        "location": location or {},
        "assumptions": assumptions or [],
        "artifacts": artifacts or {},
    }
    if diagnostics:
        finding["diagnostics"] = diagnostics
    return finding


def merge_documents(
    *,
    run_id: str | None,
    documents: list[dict[str, Any]],
    tool: str = "evidence_merge",
) -> dict[str, Any]:
    merged = new_document(run_id=run_id, tool=tool)
    for doc in documents:
        merged["findings"].extend(doc.get("findings", []))
    return merged


def env_metadata() -> dict[str, str]:
    return {
        "cwd": os.getcwd(),
        "python": command_version(["python3", "--version"]),
    }
