"""Run or import Kani evidence and emit normalized E4 findings."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from evidence import REPO, command_version, make_finding, new_document, read_json, relpath, write_json


def _legacy_finding(function: str, legacy: dict[str, Any]) -> dict[str, Any] | None:
    target_id = f"{function}:equivalence"
    for finding in legacy.get("findings", []):
        if finding.get("id") == target_id:
            return finding
    return None


def _finding_from_legacy(plan: dict, legacy_path: Path, run_id: str | None, property_key: str) -> dict[str, Any]:
    function = plan["function"]
    if property_key != "E4_phase1_equivalence_to_c2rust":
        raise SystemExit("--use-existing currently supports only E4_phase1_equivalence_to_c2rust")
    legacy = read_json(legacy_path)
    source = _legacy_finding(function, legacy)
    if source is None:
        raise SystemExit(f"no legacy Kani finding for {function} in {legacy_path}")

    checks_failed = source.get("checks_failed", -1)
    covers_total = source.get("covers_total", 0)
    covers_satisfied = source.get("covers_satisfied", 0)
    status = "pass" if checks_failed == 0 and covers_total == covers_satisfied else "fail"
    actual_status = "SUCCESS" if checks_failed == 0 else "FAILURE"
    actual_covers = "ALL_SATISFIED" if covers_total == covers_satisfied else "SOME_UNSATISFIABLE"

    doc = new_document(
        run_id=run_id,
        tool="kani",
        metadata={
            "source": "legacy_evidence",
            "legacy_evidence": relpath(legacy_path),
            "kani": legacy.get("run", {}).get("verifier", {}).get("version", "unknown"),
        },
    )
    req = plan.get("tool_requirements", {}).get(property_key, {})
    doc["findings"].append(
        make_finding(
            function=function,
            property_id=f"{function}.{property_key}",
            tool="kani",
            evidence_level="E4",
            status=status,
            kind="EQUIVALENCE",
            expected=plan.get("expected_outcomes", {}).get(property_key),
            actual={
                "status": actual_status,
                "covers": actual_covers,
                "checks_total": source.get("checks_total"),
                "checks_failed": checks_failed,
                "covers_total": covers_total,
                "covers_satisfied": covers_satisfied,
            },
            location=source.get("location", {}),
            assumptions=plan.get("trusted", []),
            artifacts={
                "legacy_evidence": relpath(legacy_path),
                "harness": req.get("harness_file", ""),
            },
        )
    )
    return doc


def _parse_kani_output(output: str) -> dict[str, Any]:
    covers_total = len(re.findall(r"\bcover\.\d+\b", output))
    covers_satisfied = len(re.findall(r"Status:\s+SATISFIED", output))
    verification_success = "VERIFICATION:- SUCCESSFUL" in output
    return {
        "status": "SUCCESS" if verification_success else "FAILURE",
        "covers": (
            "ALL_SATISFIED"
            if covers_total and covers_total == covers_satisfied
            else "NOT_REQUIRED"
            if covers_total == 0
            else "SOME_UNSATISFIABLE"
        ),
        "checks_failed": 0 if verification_success else 1,
        "covers_total": covers_total,
        "covers_satisfied": covers_satisfied,
    }


def _run_kani(plan: dict, run_id: str | None, log_path: Path | None, property_key: str) -> dict[str, Any]:
    function = plan["function"]
    req = plan.get("tool_requirements", {}).get(property_key, {})
    crate = Path(req.get("crate", "."))
    if not crate.is_absolute():
        crate = REPO / crate
    harness = req.get("harness")

    cmd = ["cargo", "kani"]
    if harness:
        cmd.extend(["--harness", harness])
    cmd.extend(req.get("kani_args", []))
    result = subprocess.run(cmd, cwd=crate, capture_output=True, text=True, timeout=600)
    output = result.stdout + "\n" + result.stderr
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output)

    actual = _parse_kani_output(output)
    status = "pass" if result.returncode == 0 and actual["status"] == "SUCCESS" else "fail"
    if actual["covers"] != "ALL_SATISFIED":
        status = "fail"

    doc = new_document(
        run_id=run_id,
        tool="kani",
        metadata={
            "cargo": command_version(["cargo", "--version"]),
            "kani": command_version(["cargo", "kani", "--version"]),
            "command": " ".join(cmd),
            "crate": relpath(crate),
        },
    )
    doc["findings"].append(
        make_finding(
            function=function,
            property_id=f"{function}.{property_key}",
            tool="kani",
            evidence_level="E4",
            status=status,
            kind="EQUIVALENCE",
            expected=plan.get("expected_outcomes", {}).get(property_key),
            actual=actual | {"returncode": result.returncode},
            location={"path": req.get("harness_file", ""), "symbol": harness or function},
            assumptions=plan.get("trusted", []),
            artifacts={"log": relpath(log_path) if log_path else "", "crate": relpath(crate)},
            diagnostics=output[-4000:] if status != "pass" else None,
        )
    )
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id")
    ap.add_argument("--log")
    ap.add_argument("--use-existing", help="Import an existing legacy evidence.json instead of running Kani")
    ap.add_argument("--property-key", default="E4_phase1_equivalence_to_c2rust")
    args = ap.parse_args(argv)

    plan = read_json(args.plan)
    if args.use_existing:
        legacy_path = Path(args.use_existing)
        if not legacy_path.is_absolute():
            legacy_path = REPO / legacy_path
        doc = _finding_from_legacy(plan, legacy_path, args.run_id, args.property_key)
    else:
        log_path = Path(args.log) if args.log else None
        doc = _run_kani(plan, args.run_id, log_path, args.property_key)
    write_json(args.out, doc)
    failed = any(f.get("status") != "pass" for f in doc.get("findings", []))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
