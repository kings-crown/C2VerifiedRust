"""Classify every function in a c2rust-transpile output by harness pattern.

Emits a CSV with one row per function, classifying each into:

  scalar_pure      - returns/takes only scalars; no pointers; ctype-pattern
  bounded_pointer  - has raw pointers but body does not touch globals; smaz-pattern
  state_mutating   - body reads/writes static mut globals; needs verification model
  ffi_or_event     - calls sokol_*/extern callbacks; not feasible for Phase 1/2

The classification is a pre-hoc filter, not a proof. A reviewer can disagree
with any row by editing the CSV; the verification pipeline does not consume
this CSV automatically.

Usage:
    python3 tools/triage_c2rust.py <pacman.rs> --out demo_inputs/pacman/inventory.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path


FN_HEADER = re.compile(
    r"^(?P<vis>pub\s+)?(?P<unsafety>unsafe\s+)?(?P<extern>extern\s+\"C\"\s+)?fn\s+(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\s*\("
)


@dataclass
class FuncRecord:
    name: str
    start_line: int
    end_line: int
    signature: str
    has_raw_ptr_param: bool
    returns_scalar: bool
    body_lines: int
    sokol_calls: int
    static_mut_refs: int
    callee_calls: list[str]
    classification: str
    phase2_score: int
    rationale: str


def _find_functions(source: str) -> list[tuple[int, int, str, str]]:
    """Return (start_line, end_line, header, body) for every function definition.

    Skips `extern { fn foo(...); }` declarations — those have no body.
    """
    lines = source.splitlines()
    funcs: list[tuple[int, int, str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = FN_HEADER.match(line)
        if not m:
            i += 1
            continue

        # Find the end of the signature (the line containing `{`).
        sig_start = i
        depth_paren = 0
        sig_end = None
        for j in range(i, len(lines)):
            for ch in lines[j]:
                if ch == "(":
                    depth_paren += 1
                elif ch == ")":
                    depth_paren -= 1
            if depth_paren == 0 and "{" in lines[j]:
                sig_end = j
                break
        if sig_end is None:
            i += 1
            continue

        header_text = "\n".join(lines[sig_start:sig_end + 1])

        # Walk forward from sig_end, balancing braces, to find body end.
        depth_brace = 0
        body_end = None
        for j in range(sig_end, len(lines)):
            for ch in lines[j]:
                if ch == "{":
                    depth_brace += 1
                elif ch == "}":
                    depth_brace -= 1
                    if depth_brace == 0:
                        body_end = j
                        break
            if body_end is not None:
                break
        if body_end is None:
            i += 1
            continue

        body_text = "\n".join(lines[sig_end + 1:body_end])
        funcs.append((sig_start + 1, body_end + 1, header_text, body_text))
        i = body_end + 1
    return funcs


def _signature_features(header: str) -> tuple[str, bool, bool]:
    """Return (compact_signature, has_raw_ptr_param, returns_scalar)."""
    compact = re.sub(r"\s+", " ", header).strip()
    has_ptr = bool(re.search(r"\*\s*(?:mut|const)\s+", compact.split(")")[0] if ")" in compact else compact))
    ret = ""
    m = re.search(r"\)\s*(?:->\s*([^\{]+))?\s*\{", compact)
    if m and m.group(1):
        ret = m.group(1).strip()
    scalar_ret = (
        ret == ""
        or "::" not in ret  # primitives like c_int, c_uint, bool, u32
        or re.fullmatch(r"::core::ffi::c_(int|uint|long|ulong|short|ushort|char|uchar|float|double|void)", ret) is not None
    )
    if "*" in ret or "&" in ret:
        scalar_ret = False
    return compact, has_ptr, scalar_ret


def _body_features(body: str) -> tuple[int, int, list[str]]:
    sokol_calls = len(re.findall(r"\b(?:sapp|sg|saudio|sgl|stm|slog|slx)_[a-z_]+\s*\(", body))
    static_mut_refs = len(re.findall(r"(?<![\w])(?:state|tmp_data)(?:\s*\.|\s*\[)|(?<!let\s)\bstatic\s+mut\s+", body))
    callees = re.findall(r"(?<![\w:])([a-z_][a-z0-9_]{2,})\s*\(", body)
    return sokol_calls, static_mut_refs, callees


def _classify(rec: dict) -> tuple[str, int, str]:
    if rec["sokol_calls"] > 0:
        return ("ffi_or_event", 0, f"calls {rec['sokol_calls']} sokol_* FFI symbols")
    if rec["static_mut_refs"] > 0:
        return ("state_mutating", 5, f"touches state struct {rec['static_mut_refs']}x")
    if rec["has_raw_ptr_param"]:
        return ("bounded_pointer", 7, "raw-pointer parameter; smaz-pattern model viable")
    if rec["returns_scalar"] and not rec["has_raw_ptr_param"]:
        # Bonus: short body suggests easy harness
        score = 10 if rec["body_lines"] <= 10 else 8
        return ("scalar_pure", score, f"scalar in/out, body {rec['body_lines']} lines, ctype-pattern")
    return ("state_mutating", 4, "non-pure, non-pointer; needs framing")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="path to c2rust-transpile output (e.g., pacman.rs)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--header", help="optional preamble file (provenance)", default=None)
    args = ap.parse_args()

    src = Path(args.source).read_text()
    funcs = _find_functions(src)

    rows: list[FuncRecord] = []
    for start, end, header, body in funcs:
        m = FN_HEADER.match(header.split("\n")[0])
        name = m.group("name") if m else "?"
        compact_sig, has_ptr, scalar_ret = _signature_features(header)
        sokol_calls, static_mut_refs, callees = _body_features(body)
        body_lines = end - start
        feat = {
            "has_raw_ptr_param": has_ptr,
            "returns_scalar": scalar_ret,
            "body_lines": body_lines,
            "sokol_calls": sokol_calls,
            "static_mut_refs": static_mut_refs,
        }
        cls, score, rationale = _classify(feat)
        rows.append(FuncRecord(
            name=name,
            start_line=start,
            end_line=end,
            signature=compact_sig[:200],
            has_raw_ptr_param=has_ptr,
            returns_scalar=scalar_ret,
            body_lines=body_lines,
            sokol_calls=sokol_calls,
            static_mut_refs=static_mut_refs,
            callee_calls=callees,
            classification=cls,
            phase2_score=score,
            rationale=rationale,
        ))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        if args.header:
            f.write(Path(args.header).read_text())
        w = csv.writer(f)
        w.writerow([
            "name", "start_line", "end_line", "body_lines",
            "classification", "phase2_score", "rationale",
            "has_raw_ptr_param", "returns_scalar",
            "sokol_calls", "static_mut_refs",
            "signature",
        ])
        for r in sorted(rows, key=lambda r: (-r.phase2_score, r.start_line)):
            w.writerow([
                r.name, r.start_line, r.end_line, r.body_lines,
                r.classification, r.phase2_score, r.rationale,
                r.has_raw_ptr_param, r.returns_scalar,
                r.sokol_calls, r.static_mut_refs,
                r.signature.replace("\n", " "),
            ])

    by_cls: dict[str, int] = {}
    for r in rows:
        by_cls[r.classification] = by_cls.get(r.classification, 0) + 1
    print(f"[+] {len(rows)} functions classified")
    for k in sorted(by_cls):
        print(f"    {k}: {by_cls[k]}")
    print(f"[+] inventory -> {out_path}")
    print(f"\nTop Phase 2 candidates (score >= 7):")
    for r in sorted(rows, key=lambda r: (-r.phase2_score, r.body_lines, r.start_line))[:15]:
        if r.phase2_score >= 7:
            print(f"    [{r.classification}, score={r.phase2_score}] {r.name} (line {r.start_line}, {r.body_lines} body lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
