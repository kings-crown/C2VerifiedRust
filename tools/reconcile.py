"""Reconcile pre-hoc plans against post-hoc evidence.

Inputs:
  - plans/<func>.json: pre-hoc Verification Plans
  - demo_codex/c_ctype_5/evidence.json: Kani equivalence findings
  - demo_codex/e0_no_unsafe_marker.json: E0_no_unsafe_marker gate output

For each (plan, function) pair, compare each `expected_outcomes` entry
against the actual evidence. Verdicts per key:
  - consistent : actual matches expected
  - divergent  : actual differs from expected
  - unverified : the gate did not run (only acceptable for `optional`)

A plan is "honored" iff every required key has a `consistent` verdict.

Usage:
  python3 tools/reconcile.py
"""

from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PLANS_DIR = REPO / "plans"
KANI_EVIDENCE = REPO / "demo_codex" / "c_ctype_5" / "evidence.json"
NO_UNSAFE_EVIDENCE = REPO / "demo_codex" / "e0_no_unsafe_marker.json"


def _status_to_e0(status: str) -> str:
    return "PASS" if status == "pass" else "FAIL"


def _load(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _kani_actual_for(func: str, kani: dict) -> dict | None:
    fid = f"{func}:equivalence"
    for finding in kani.get("findings", []):
        if finding.get("id") == fid:
            return finding
    return None


def _no_unsafe_actual_for(func: str, ev: dict) -> dict | None:
    for f in ev.get("findings", []):
        if f.get("function") == func:
            return f
    return None


def _verdict_e0_compile(plan_outcome: str, kani: dict | None) -> tuple[str, str]:
    """We treat a successful Kani run as proof the candidate compiled."""
    if kani is None:
        return ("unverified", "no Kani evidence for this function")
    actual = "PASS" if kani.get("status") == "discharged" else "FAIL"
    if actual == plan_outcome:
        return ("consistent", f"actual={actual}")
    return ("divergent", f"plan={plan_outcome}, actual={actual}")


def _verdict_e0_no_unsafe(plan_outcome: str, ev: dict | None) -> tuple[str, str]:
    if ev is None:
        return ("unverified", "no E0_no_unsafe_marker gate output for this function")
    actual = ev.get("outcome")
    if actual == plan_outcome:
        return ("consistent", f"actual={actual}")
    diag = ev.get("diagnostic_excerpt", "").splitlines()
    diag_one = next((d for d in diag if "error" in d.lower()), "(see e0_no_unsafe_marker.json)")
    return ("divergent", f"plan={plan_outcome}, actual={actual}: {diag_one}")


def _verdict_e4(plan_outcome: dict, kani: dict | None) -> tuple[str, str]:
    if kani is None:
        return ("unverified", "no Kani evidence for this function")
    expected_status = plan_outcome.get("status")
    expected_covers = plan_outcome.get("covers")
    actual_status = "SUCCESS" if kani.get("checks_failed", -1) == 0 else "FAILURE"
    if kani.get("covers_total") == kani.get("covers_satisfied"):
        actual_covers = "ALL_SATISFIED"
    elif kani.get("covers_satisfied", 0) < kani.get("covers_total", 0):
        actual_covers = "SOME_UNSATISFIABLE"
    else:
        actual_covers = "NOT_REQUIRED"
    if actual_status == expected_status and actual_covers == expected_covers:
        return ("consistent", f"status={actual_status}, covers={actual_covers}")
    return ("divergent",
            f"plan=({expected_status}, {expected_covers}), actual=({actual_status}, {actual_covers})")


def reconcile_one(plan: dict, kani_ev: dict | None, no_unsafe_ev: dict | None) -> dict:
    func = plan["function"]
    checkable = plan["checkable"]
    expected = plan["expected_outcomes"]
    kani_record = _kani_actual_for(func, kani_ev) if kani_ev else None
    no_unsafe_record = _no_unsafe_actual_for(func, no_unsafe_ev) if no_unsafe_ev else None

    per_key = {}
    for key, exp in expected.items():
        if key == "E0_compile":
            v, d = _verdict_e0_compile(exp, kani_record)
        elif key == "E0_no_unsafe_marker":
            v, d = _verdict_e0_no_unsafe(exp, no_unsafe_record)
        elif key.startswith("E4"):
            v, d = _verdict_e4(exp, kani_record)
        else:
            v, d = ("unverified", "no actual-outcome handler for this key")
        per_key[key] = {
            "verdict": v,
            "detail": d,
            "required": checkable.get(key) == "required",
        }

    required_keys = {k for k, v in checkable.items() if v == "required"}
    honored = all(
        per_key.get(k, {}).get("verdict") == "consistent"
        for k in required_keys
    )

    return {
        "function": func,
        "ceiling_claimed": plan["ceiling"],
        "trusted_count": len(plan.get("trusted", [])),
        "per_key": per_key,
        "honored": honored,
        "first_party_summary": (
            "HONORED" if honored else
            "DIVERGENT (" + ", ".join(
                k for k in required_keys
                if per_key.get(k, {}).get("verdict") != "consistent"
            ) + ")"
        ),
    }


def _normalized_actual_for(func: str, key: str, normalized: dict) -> dict | None:
    pid = f"{func}.{key}"
    for finding in normalized.get("findings", []):
        if finding.get("property_id") == pid:
            return finding
    return None


def _verdict_normalized(key: str, expected, finding: dict | None) -> tuple[str, str]:
    if finding is None:
        return ("unverified", "no normalized evidence for this property")
    status = finding.get("status")
    actual = finding.get("actual", {})
    if key.startswith("E4"):
        actual_status = actual.get("status") or ("SUCCESS" if status == "pass" else "FAILURE")
        actual_covers = actual.get("covers", "NOT_REQUIRED")
        expected_status = expected.get("status")
        expected_covers = expected.get("covers")
        if actual_status == expected_status and actual_covers == expected_covers:
            return ("consistent", f"status={actual_status}, covers={actual_covers}")
        return (
            "divergent",
            f"plan=({expected_status}, {expected_covers}), actual=({actual_status}, {actual_covers})",
        )
    actual_e0 = _status_to_e0(status)
    if actual_e0 == expected:
        return ("consistent", f"actual={actual_e0}")
    detail = finding.get("diagnostics") or actual
    return ("divergent", f"plan={expected}, actual={actual_e0}: {str(detail)[:240]}")


def reconcile_one_normalized(plan: dict, normalized: dict) -> dict:
    func = plan["function"]
    checkable = plan["checkable"]
    expected = plan["expected_outcomes"]
    per_key = {}

    for key, exp in expected.items():
        finding = _normalized_actual_for(func, key, normalized)
        v, d = _verdict_normalized(key, exp, finding)
        per_key[key] = {
            "verdict": v,
            "detail": d,
            "required": checkable.get(key) == "required",
            "property_id": f"{func}.{key}",
        }

    required_keys = {k for k, v in checkable.items() if v == "required"}
    honored = all(
        per_key.get(k, {}).get("verdict") == "consistent"
        for k in required_keys
    )
    return {
        "function": func,
        "ceiling_claimed": plan["ceiling"],
        "trusted_count": len(plan.get("trusted", [])),
        "per_key": per_key,
        "honored": honored,
        "first_party_summary": (
            "HONORED" if honored else
            "DIVERGENT (" + ", ".join(
                k for k in required_keys
                if per_key.get(k, {}).get("verdict") != "consistent"
            ) + ")"
        ),
    }


def _main_legacy() -> int:
    kani_ev = _load(KANI_EVIDENCE)
    no_unsafe_ev = _load(NO_UNSAFE_EVIDENCE)

    if kani_ev is None:
        print(f"WARNING: {KANI_EVIDENCE} missing — Kani-backed checks will be unverified",
              file=sys.stderr)
    if no_unsafe_ev is None:
        print(f"WARNING: {NO_UNSAFE_EVIDENCE} missing — run check_no_unsafe_marker.py first",
              file=sys.stderr)

    rows = []
    plan_paths = sorted(PLANS_DIR.glob("*.json"))
    for pp in plan_paths:
        plan = json.loads(pp.read_text())
        rows.append(reconcile_one(plan, kani_ev, no_unsafe_ev))

    out = REPO / "demo_codex" / "reconciliation.json"
    out.write_text(json.dumps({"reconciliations": rows}, indent=2))

    honored_count = sum(1 for r in rows if r["honored"])
    width = max(len(r["function"]) for r in rows)
    print(f"\n{'function'.ljust(width)} | summary")
    print(f"{'-' * width}-+-{'-' * 60}")
    for r in rows:
        print(f"{r['function'].ljust(width)} | {r['first_party_summary']}")
    print(f"\nHonored: {honored_count}/{len(rows)}")
    print(f"[+] full reconciliation -> {out}")

    return 0 if honored_count == len(rows) else 1


def _main_normalized(plan_path: Path, evidence_path: Path, out_path: Path | None) -> int:
    plan = json.loads(plan_path.read_text())
    evidence = json.loads(evidence_path.read_text())
    row = reconcile_one_normalized(plan, evidence)
    out = {
        "schema_version": 1,
        "run": evidence.get("run", {}),
        "reconciliations": [row],
    }
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2) + "\n")

    print(f"{row['function']} | {row['first_party_summary']}")
    if out_path:
        print(f"[+] reconciliation -> {out_path}")
    return 0 if row["honored"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", help="Single Verification Plan for normalized reconciliation")
    ap.add_argument("--evidence", help="Normalized evidence.json")
    ap.add_argument("--out", help="Output reconciliation JSON")
    args = ap.parse_args(argv)

    if args.plan or args.evidence:
        if not args.plan or not args.evidence:
            print("--plan and --evidence must be provided together", file=sys.stderr)
            return 2
        return _main_normalized(
            Path(args.plan),
            Path(args.evidence),
            Path(args.out) if args.out else None,
        )
    return _main_legacy()


if __name__ == "__main__":
    sys.exit(main())
