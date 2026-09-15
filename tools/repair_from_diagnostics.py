"""Create a repair prompt from divergent normalized evidence.

This is the handoff point for the HCSS post-hoc diagnostics loop. The script
does not mutate code by default; it packages the failing tool output into a
bounded repair request that an agent/LLM can consume.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evidence import read_json


def _first_failure(evidence: dict) -> dict | None:
    for finding in evidence.get("findings", []):
        if finding.get("status") != "pass":
            return finding
    return None


def _prompt(plan: dict, finding: dict) -> str:
    function = plan["function"]
    property_id = finding.get("property_id", "")
    diagnostics = finding.get("diagnostics", "")
    artifacts = finding.get("artifacts", {})
    raw_candidate = artifacts.get("raw_candidate", "")
    return f"""You are repairing one Rust translation candidate.

Function: {function}
Failed property: {property_id}
Raw candidate: {raw_candidate or "(see plan tool_requirements)"}

Constraint:
- Make the smallest edit that addresses the diagnostic.
- Preserve the function's behavior.
- Do not change the function name or signature semantics.
- Do not introduce unsafe Rust.
- If the failure is due to c2rust ABI/linkage attributes in a Rust-only consumer, remove only the unnecessary attributes such as #[no_mangle], #[linkage = "..."], and any unnecessary unsafe marker.

Diagnostic:
```text
{diagnostics}
```

Return only the repaired Rust function body and its required attributes/imports.
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    plan = read_json(args.plan)
    evidence = read_json(args.evidence)
    failure = _first_failure(evidence)
    if failure is None:
        print("no failing evidence found", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_prompt(plan, failure))
    print(f"[+] repair prompt -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
