"""Fuse multiple normalized findings into a conservative E5 finding."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evidence import make_finding, new_document, read_json, write_json


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--property-key", default="E5_cross_tool")
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id")
    args = ap.parse_args(argv)

    plan = read_json(args.plan)
    evidence = read_json(args.evidence)
    function = plan["function"]
    req = plan.get("tool_requirements", {}).get(args.property_key, {})
    inputs = req.get("inputs", [])
    by_id = {f.get("property_id"): f for f in evidence.get("findings", [])}
    selected = [by_id.get(pid) for pid in inputs]

    missing = [pid for pid, finding in zip(inputs, selected) if finding is None]
    statuses = [f.get("status") for f in selected if f is not None]
    agrees = len(inputs) >= 2 and not missing and all(status == "pass" for status in statuses)
    status = "pass" if agrees else "fail"

    doc = new_document(run_id=args.run_id or evidence.get("run", {}).get("run_id"), tool="evidence_fusion")
    doc["findings"].append(
        make_finding(
            function=function,
            property_id=f"{function}.{args.property_key}",
            tool="evidence_fusion",
            evidence_level="E5",
            status=status,
            kind="CROSS_TOOL_AGREEMENT",
            expected=plan.get("expected_outcomes", {}).get(args.property_key),
            actual={
                "inputs": inputs,
                "missing": missing,
                "statuses": statuses,
                "agreement": "AGREES" if agrees else "DISAGREES",
            },
            assumptions=["underlying tools check compatible property ids"],
        )
    )
    write_json(args.out, doc)
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
