"""Run the E0 compile gate and emit normalized evidence."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from evidence import REPO, command_version, make_finding, new_document, read_json, relpath, write_json


def _plan_req(plan: dict, key: str) -> dict:
    return plan.get("tool_requirements", {}).get(key, {})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", help="Verification Plan JSON")
    ap.add_argument("--crate", help="Crate directory to build")
    ap.add_argument("--function", help="Function name when no plan is provided")
    ap.add_argument("--out", required=True, help="Normalized evidence output path")
    ap.add_argument("--run-id")
    args = ap.parse_args(argv)

    plan = read_json(args.plan) if args.plan else None
    function = args.function or (plan or {}).get("function", "unknown")
    req = _plan_req(plan or {}, "E0_compile")
    crate = Path(args.crate or req.get("crate", "."))
    if not crate.is_absolute():
        crate = REPO / crate

    cmd = ["cargo", "build", "--quiet", "--message-format=short"]
    result = subprocess.run(cmd, cwd=crate, capture_output=True, text=True, timeout=180)
    stderr = result.stderr[-4000:]
    stdout = result.stdout[-4000:]
    status = "pass" if result.returncode == 0 else "fail"

    doc = new_document(
        run_id=args.run_id,
        tool="cargo_build",
        metadata={
            "cargo": command_version(["cargo", "--version"]),
            "command": " ".join(cmd),
            "crate": relpath(crate),
        },
    )
    doc["findings"].append(
        make_finding(
            function=function,
            property_id=f"{function}.E0_compile",
            tool="cargo_build",
            evidence_level="E0",
            status=status,
            kind="COMPILE",
            expected=(plan or {}).get("expected_outcomes", {}).get("E0_compile"),
            actual={
                "returncode": result.returncode,
                "stdout_excerpt": stdout,
                "stderr_excerpt": stderr,
            },
            location={"path": relpath(crate / "Cargo.toml"), "symbol": function},
            artifacts={"crate": relpath(crate)},
            diagnostics=stderr or stdout,
        )
    )
    write_json(args.out, doc)
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
