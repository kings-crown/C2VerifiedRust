"""E0_no_unsafe_marker gate.

For each <func>_safe.rs in demo_codex/<func>/, build a tiny wrapper crate
that imports the file under `#![forbid(unsafe_code)]` and runs `cargo
build`. PASS if the build succeeds; FAIL with the rustc diagnostic
otherwise.

The gate runs in a temp directory so it leaves no state in the repo.

Usage:
    python3 tools/check_no_unsafe_marker.py demo_codex/c_isalpha
    python3 tools/check_no_unsafe_marker.py demo_codex/c_isalpha demo_codex/c_isspace ...
    python3 tools/check_no_unsafe_marker.py demo_codex/c_isalpha \
        --evidence-out runs/manual/evidence/E0_no_unsafe_marker.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from evidence import command_version, make_finding, new_document, relpath, write_json


CARGO_TOML = """[package]
name = "no_unsafe_probe"
version = "0.0.1"
edition = "2021"

[dependencies]
libc = "0.2"

[lib]
path = "src/lib.rs"
"""

LIB_RS = """#![forbid(unsafe_code)]

mod candidate;
"""


def _run_one(safe_rs: Path) -> dict:
    func = safe_rs.stem.removesuffix("_safe")
    candidate = safe_rs.read_text()

    with tempfile.TemporaryDirectory(prefix="no_unsafe_probe_") as tmp:
        tmp = Path(tmp)
        (tmp / "src").mkdir()
        (tmp / "Cargo.toml").write_text(CARGO_TOML)
        (tmp / "src" / "lib.rs").write_text(LIB_RS)
        (tmp / "src" / "candidate.rs").write_text(candidate)

        result = subprocess.run(
            ["cargo", "build", "--quiet", "--message-format=short"],
            cwd=tmp,
            capture_output=True,
            text=True,
            timeout=120,
        )

        passed = result.returncode == 0
        diagnostic = ""
        if not passed:
            stderr = result.stderr
            lines = [
                ln for ln in stderr.splitlines()
                if "error" in ln.lower() or "unsafe" in ln.lower()
            ]
            diagnostic = "\n".join(lines[:20]) or stderr[-2000:]

        signature_unsafe = bool(re.search(r"\bpub\s+(?:.*\s+)?unsafe\s+(?:extern\s+\"C\"\s+)?fn\s+", candidate))
        return {
            "function": func,
            "safe_rs": str(safe_rs),
            "passed": passed,
            "outcome": "PASS" if passed else "FAIL",
            "signature_marked_unsafe": signature_unsafe,
            "diagnostic_excerpt": diagnostic,
        }


def _normalized_doc(results: list[dict], run_id: str | None) -> dict:
    doc = new_document(
        run_id=run_id,
        tool="rustc_forbid_unsafe",
        metadata={
            "cargo": command_version(["cargo", "--version"]),
            "rustc": command_version(["rustc", "--version"]),
        },
    )
    for r in results:
        func = r["function"]
        doc["findings"].append(
            make_finding(
                function=func,
                property_id=f"{func}.E0_no_unsafe_marker",
                tool="rustc_forbid_unsafe",
                evidence_level="E0",
                status="pass" if r["passed"] else "fail",
                kind="NO_UNSAFE_MARKER",
                expected="PASS",
                actual={
                    "outcome": r["outcome"],
                    "signature_marked_unsafe": r["signature_marked_unsafe"],
                },
                location={"path": relpath(r["safe_rs"]), "symbol": func},
                artifacts={"raw_candidate": relpath(r["safe_rs"])},
                diagnostics=r.get("diagnostic_excerpt") or None,
            )
        )
    return doc


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="demo_codex/<func> directories")
    ap.add_argument("--out", default="demo_codex/e0_no_unsafe_marker.json")
    ap.add_argument("--evidence-out", help="Normalized evidence output path")
    ap.add_argument("--run-id")
    ap.add_argument("--fail-on-failures", action="store_true")
    args = ap.parse_args(argv[1:])

    if shutil.which("cargo") is None:
        print("cargo not found on PATH", file=sys.stderr)
        return 2

    results = []
    for arg in args.paths:
        d = Path(arg)
        candidates = list(d.glob("*_safe.rs"))
        if not candidates:
            print(f"[SKIP] {d}: no <func>_safe.rs found", file=sys.stderr)
            continue
        for safe_rs in candidates:
            r = _run_one(safe_rs)
            results.append(r)
            tag = "PASS" if r["passed"] else "FAIL"
            mark = "marked unsafe" if r["signature_marked_unsafe"] else "no unsafe in signature"
            print(f"[{tag}] {r['function']}: signature {mark}")
            if not r["passed"] and r["diagnostic_excerpt"]:
                excerpt = r["diagnostic_excerpt"].splitlines()
                for ln in excerpt[:3]:
                    print(f"        {ln}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"findings": results}, indent=2) + "\n")
    print(f"\n[+] aggregated -> {out}")
    if args.evidence_out:
        write_json(args.evidence_out, _normalized_doc(results, args.run_id))
        print(f"[+] normalized evidence -> {args.evidence_out}")

    if args.fail_on_failures and any(not r["passed"] for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
