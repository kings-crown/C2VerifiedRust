"""Run Miri tests and emit normalized E3 evidence for concrete executions."""

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
    ap.add_argument("--test-filter", default="")
    args = ap.parse_args(argv)

    plan = read_json(args.plan) if args.plan else None
    function = args.function or (plan or {}).get("function", "unknown")
    req = (plan or {}).get("tool_requirements", {}).get("E3_miri_concrete_ub", {})
    crate = Path(args.crate or req.get("crate", "."))
    if not crate.is_absolute():
        crate = REPO / crate

    cmd = ["cargo", "+nightly", "miri", "test"]
    test_filter = args.test_filter or req.get("test_filter", "")
    if test_filter:
        cmd.append(test_filter)

    result = subprocess.run(cmd, cwd=crate, capture_output=True, text=True, timeout=300)
    status = "pass" if result.returncode == 0 else "fail"
    stderr = result.stderr[-4000:]
    stdout = result.stdout[-4000:]

    doc = new_document(
        run_id=args.run_id,
        tool="miri",
        metadata={
            "cargo": command_version(["cargo", "--version"]),
            "miri": command_version(["cargo", "+nightly", "miri", "--version"]),
            "command": " ".join(cmd),
            "crate": relpath(crate),
        },
    )
    doc["findings"].append(
        make_finding(
            function=function,
            property_id=f"{function}.E3_miri_concrete_ub",
            tool="miri",
            evidence_level="E3",
            status=status,
            kind="CONCRETE_UB",
            expected=(plan or {}).get("expected_outcomes", {}).get("E3_miri_concrete_ub"),
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
