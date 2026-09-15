"""Run Clippy and emit normalized E1 evidence."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from evidence import REPO, command_version, make_finding, new_document, read_json, relpath, write_json


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan")
    ap.add_argument("--crate")
    ap.add_argument("--function")
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id")
    ap.add_argument("--deny-warnings", action="store_true")
    args = ap.parse_args(argv)

    plan = read_json(args.plan) if args.plan else None
    function = args.function or (plan or {}).get("function", "unknown")
    req = (plan or {}).get("tool_requirements", {}).get("E1_clippy", {})
    crate = Path(args.crate or req.get("crate", "."))
    if not crate.is_absolute():
        crate = REPO / crate

    cmd = ["cargo", "clippy", "--all-targets"]
    if args.deny_warnings or req.get("deny_warnings"):
        cmd.extend(["--", "-D", "warnings"])

    result = subprocess.run(cmd, cwd=crate, capture_output=True, text=True, timeout=240)
    status = "pass" if result.returncode == 0 else "fail"
    stderr = result.stderr[-4000:]
    stdout = result.stdout[-4000:]

    doc = new_document(
        run_id=args.run_id,
        tool="clippy",
        metadata={
            "cargo": command_version(["cargo", "--version"]),
            "command": " ".join(cmd),
            "crate": relpath(crate),
        },
    )
    doc["findings"].append(
        make_finding(
            function=function,
            property_id=f"{function}.E1_clippy",
            tool="clippy",
            evidence_level="E1",
            status=status,
            kind="LINT",
            expected=(plan or {}).get("expected_outcomes", {}).get("E1_clippy"),
            actual={"returncode": result.returncode},
            location={"path": relpath(crate / "Cargo.toml"), "symbol": function},
            artifacts={"crate": relpath(crate)},
            diagnostics=stderr or stdout,
        )
    )
    write_json(args.out, doc)
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
