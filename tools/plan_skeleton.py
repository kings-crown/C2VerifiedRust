"""Generate a mechanically filled Verification Plan skeleton.

This is the missing bridge between ``triage_c2rust.py`` and hand-authored
plans. It reads a c2rust-transpile output, optionally joins the matching
inventory CSV row, derives the low-risk fields, and emits a JSON document that
passes ``plan_check.py --stage pre`` while leaving human-judgment fields marked
with explicit TODOs.

Usage:
    python3 tools/plan_skeleton.py demo_inputs/pacman/pacman.rs \
      --function valid_tile_pos \
      --c-source demo_inputs/pacman/pacman.c \
      --inventory demo_inputs/pacman/inventory.csv \
      --crate demo_inputs/pacman_valid_tile_pos_kani \
      --spec specs/pacman_valid_tile_pos.md \
      --artifact-mode verbatim_model \
      --require E4_phase2_equivalence_to_spec \
      --out /tmp/valid_tile_pos.skeleton.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import plan_check
import triage_c2rust


REPO = Path(__file__).resolve().parents[1]

LEVEL_CHOICES = sorted(plan_check.VALID_LEVEL_IDS)


@dataclass
class FunctionAnalysis:
    name: str
    start_line: int
    end_line: int
    header: str
    body: str
    compact_signature: str
    has_raw_ptr_param: bool
    returns_scalar: bool
    body_lines: int
    sokol_calls: int
    static_mut_refs: int
    classification: str
    phase2_score: int
    rationale: str


def _repo_relative(path: str | Path) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            return p.relative_to(REPO).as_posix()
        except ValueError:
            return p.as_posix()
    return p.as_posix()


def _read_inventory_row(path: Path, function: str) -> dict[str, str] | None:
    raw_lines = path.read_text().splitlines()
    csv_text = "\n".join(line for line in raw_lines if not line.lstrip().startswith("#"))
    if not csv_text.strip():
        return None
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("name") == function:
            return row
    return None


def _analyze_function(rust_path: Path, function: str) -> FunctionAnalysis:
    source = rust_path.read_text()
    for start, end, header, body in triage_c2rust._find_functions(source):
        first = header.splitlines()[0]
        m = triage_c2rust.FN_HEADER.match(first)
        if not m or m.group("name") != function:
            continue
        compact, has_ptr, scalar_ret = triage_c2rust._signature_features(header)
        sokol_calls, static_mut_refs, _ = triage_c2rust._body_features(body)
        body_lines = end - start
        cls, score, rationale = triage_c2rust._classify(
            {
                "has_raw_ptr_param": has_ptr,
                "returns_scalar": scalar_ret,
                "body_lines": body_lines,
                "sokol_calls": sokol_calls,
                "static_mut_refs": static_mut_refs,
            }
        )
        return FunctionAnalysis(
            name=function,
            start_line=start,
            end_line=end,
            header=header,
            body=body,
            compact_signature=compact,
            has_raw_ptr_param=has_ptr,
            returns_scalar=scalar_ret,
            body_lines=body_lines,
            sokol_calls=sokol_calls,
            static_mut_refs=static_mut_refs,
            classification=cls,
            phase2_score=score,
            rationale=rationale,
        )
    raise SystemExit(f"function {function!r} not found in {rust_path}")


def _apply_inventory(analysis: FunctionAnalysis, row: dict[str, str] | None) -> FunctionAnalysis:
    if row is None:
        return analysis
    return FunctionAnalysis(
        name=analysis.name,
        start_line=int(row.get("start_line") or analysis.start_line),
        end_line=int(row.get("end_line") or analysis.end_line),
        header=analysis.header,
        body=analysis.body,
        compact_signature=analysis.compact_signature,
        has_raw_ptr_param=(row.get("has_raw_ptr_param") or str(analysis.has_raw_ptr_param)) == "True",
        returns_scalar=(row.get("returns_scalar") or str(analysis.returns_scalar)) == "True",
        body_lines=int(row.get("body_lines") or analysis.body_lines),
        sokol_calls=int(row.get("sokol_calls") or analysis.sokol_calls),
        static_mut_refs=int(row.get("static_mut_refs") or analysis.static_mut_refs),
        classification=row.get("classification") or analysis.classification,
        phase2_score=int(row.get("phase2_score") or analysis.phase2_score),
        rationale=row.get("rationale") or analysis.rationale,
    )


def _find_matching_paren(text: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(text)):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unbalanced function signature")


def _split_params(params: str) -> list[str]:
    if not params.strip():
        return []
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(params):
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth -= 1
        elif ch == "," and depth == 0:
            part = params[start:i].strip()
            if part:
                parts.append(part)
            start = i + 1
    tail = params[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _normalize_param(param: str) -> str:
    param = re.sub(r"^\s*mut\s+", "", param.strip())
    param = re.sub(r":\s*mut\s+", ": ", param)
    return param


def _extract_plan_signature(header: str, function: str) -> str:
    compact = re.sub(r"\s+", " ", header).strip()
    fn_marker = f"fn {function}"
    fn_idx = compact.find(fn_marker)
    if fn_idx < 0:
        raise ValueError(f"could not find {fn_marker!r} in function header")
    open_idx = compact.find("(", fn_idx)
    close_idx = _find_matching_paren(compact, open_idx)
    params = ", ".join(_normalize_param(p) for p in _split_params(compact[open_idx + 1:close_idx]))
    rest = compact[close_idx + 1:]
    rest = rest.split("{", 1)[0].strip()
    ret = ""
    if rest.startswith("->"):
        ret = " -> " + rest[2:].strip()
    return f"({params}){ret}"


def _param_types(signature: str) -> list[tuple[str, str]]:
    inner = signature[1:signature.rfind(")")] if signature.startswith("(") else signature
    params = []
    for param in _split_params(inner):
        if ":" not in param:
            params.append((param.strip(), ""))
            continue
        name, ty = param.split(":", 1)
        params.append((name.strip(), ty.strip()))
    return params


def _parse_struct_fields(source: str) -> dict[str, list[tuple[str, str]]]:
    structs: dict[str, list[tuple[str, str]]] = {}
    pat = re.compile(r"(?:pub\s+)?struct\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{(?P<body>.*?)^\}", re.M | re.S)
    for m in pat.finditer(source):
        fields: list[tuple[str, str]] = []
        for line in m.group("body").splitlines():
            fm = re.match(r"\s*(?:pub\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^,]+),?", line)
            if fm:
                fields.append((fm.group(1), fm.group(2).strip()))
        if fields:
            structs[m.group(1)] = fields
    return structs


def _type_atom(ty: str) -> str:
    ty = ty.strip()
    ty = re.sub(r"\s+", " ", ty)
    ty = ty.replace("::core::ffi::", "")
    ty = ty.replace("libc::", "")
    ty = ty.strip("*& ")
    mapping = {
        "c_int": "i32",
        "int": "i32",
        "int32_t": "i32",
        "i32": "i32",
        "c_uint": "u32",
        "uint32_t": "u32",
        "u32": "u32",
        "c_short": "i16",
        "int16_t": "i16",
        "__int16_t": "i16",
        "i16": "i16",
        "c_ushort": "u16",
        "uint16_t": "u16",
        "u16": "u16",
        "c_char": "c_char",
        "int8_t": "i8",
        "i8": "i8",
        "c_uchar": "u8",
        "uint8_t": "u8",
        "u8": "u8",
        "bool": "bool",
    }
    return mapping.get(ty, re.sub(r"[^A-Za-z0-9_]+", "_", ty).strip("_") or "unknown")


def _derive_kind(
    *,
    analysis: FunctionAnalysis,
    signature: str,
) -> str:
    params = _param_types(signature)
    params_text = " ".join(ty for _, ty in params)
    if "..." in params_text:
        return "varargs"
    if analysis.classification == "state_mutating":
        return "globals"
    if analysis.has_raw_ptr_param:
        if re.search(r"\b(?:c_char|u8|uint8_t|int8_t)\b", params_text) and re.search(
            r"\b(?:len|length|size|cap|capacity|outlen|inlen)\b", signature
        ):
            return "bytes"
        return "pointer_struct"
    if len(params) <= 1:
        return "scalar"
    return "scalar_list"


def _derive_domain(kind: str, signature: str, rust_source: str) -> str:
    params = _param_types(signature)
    if kind == "varargs":
        return "TODO_varargs_domain"
    if kind == "globals":
        return "TODO_global_state_domain"
    if kind == "bytes":
        return "TODO_bounded_byte_buffers"
    if kind == "pointer_struct":
        return "TODO_bounded_pointer_domain"
    if not params:
        return "unit"

    structs = _parse_struct_fields(rust_source)
    atoms: list[str] = []
    for _, ty in params:
        base = ty.strip()
        if base in structs:
            fields = structs[base]
            field_atoms = [_type_atom(field_ty) for _, field_ty in fields]
            if len(field_atoms) == 2 and field_atoms[0] == field_atoms[1]:
                atoms.append(f"{base}_{field_atoms[0]}_pair")
            else:
                atoms.append(f"{base}_{'_'.join(field_atoms[:4])}")
        else:
            atoms.append(_type_atom(base))

    if kind == "scalar" and len(atoms) == 1:
        return f"full_{atoms[0]}"
    return "full_" + "_".join(atoms)


def _find_c_line(c_source: Path | None, function: str, explicit_line: int | None) -> int:
    if explicit_line is not None:
        return explicit_line
    if c_source is None:
        return 1
    lines = c_source.read_text(errors="replace").splitlines()
    name_re = re.compile(rf"\b{re.escape(function)}\s*\(")
    non_definition_re = re.compile(r"^(?:if|while|for|switch|return|assert)\s*\(")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not name_re.search(line):
            continue
        if (
            non_definition_re.match(stripped)
            or stripped.startswith(("*", "/*", "//"))
            or stripped.endswith("...")
        ):
            continue
        window = "\n".join(lines[i:min(i + 8, len(lines))])
        before_body = window.split("{", 1)[0]
        if "{" in window and ";" not in before_body:
            return i + 1
    return 1


def _detect_side_effects(analysis: FunctionAnalysis) -> str:
    body = analysis.body
    if analysis.sokol_calls or re.search(r"\b(?:open|read|write|close|printf|fprintf|puts|putchar)\s*\(", body):
        return "syscalls"
    if re.search(r"\b(?:malloc|calloc|realloc|free|Vec::|Box::new)\s*\(", body):
        return "allocates"
    if analysis.static_mut_refs:
        if re.search(r"\b(?:state|tmp_data)(?:\s*\.|\s*\[).*=", body):
            return "writes_globals"
        return "reads_globals"
    if analysis.has_raw_ptr_param and re.search(
        r"(?:\*\s*[A-Za-z_][A-Za-z0-9_]*\s*=|\.write\s*\(|memcpy\s*\(|copy_nonoverlapping\s*\()",
        body,
    ):
        return "writes_output_buffer"
    return "none"


def _derive_determinism(analysis: FunctionAnalysis, side_effects: str) -> str:
    if side_effects == "syscalls" or analysis.classification == "ffi_or_event":
        return "nondeterministic"
    if analysis.has_raw_ptr_param:
        return "partial"
    return "total"


def _default_checkable(classification: str, artifact_mode: str) -> OrderedDict[str, str]:
    checkable: OrderedDict[str, str] = OrderedDict()
    checkable["E0_compile"] = "required"

    if artifact_mode == "verbatim_model":
        checkable["E0_no_unsafe_marker"] = "not_feasible"
        checkable["E4_phase1_equivalence_to_c2rust"] = "not_feasible"
    else:
        checkable["E0_no_unsafe_marker"] = "optional"
        checkable["E4_phase1_equivalence_to_c2rust"] = "optional"

    if classification == "ffi_or_event":
        checkable["E4_phase1_equivalence_to_c2rust"] = "not_feasible"
        checkable["E4_phase2_equivalence_to_spec"] = "not_feasible"
    else:
        checkable["E4_phase2_equivalence_to_spec"] = "optional"

    checkable["E5_cross_tool"] = "optional"
    return checkable


def _apply_required_overrides(checkable: OrderedDict[str, str], required: list[str]) -> None:
    for level in required:
        if level not in checkable:
            checkable[level] = "required"
        elif checkable[level] == "not_feasible":
            raise SystemExit(f"cannot require {level}: default status is not_feasible")
        else:
            checkable[level] = "required"


def _expected_for(level: str) -> Any:
    if level.startswith("E4"):
        return {"status": "SUCCESS", "covers": "ALL_SATISFIED"}
    if level == "E5_cross_tool":
        return "AGREES"
    return "PASS"


def _tool_requirements(
    *,
    checkable: OrderedDict[str, str],
    function: str,
    classification: str,
    domain: str,
    c2rust_path: str,
    crate: str | None,
    harness_file: str | None,
    raw_candidate: str | None,
    spec: str | None,
    verification_model: str | None,
) -> OrderedDict[str, Any]:
    reqs: OrderedDict[str, Any] = OrderedDict()
    crate_path = crate or "TODO: path/to/verification_crate"
    harness_path = harness_file or "TODO: path/to/proofs.rs"

    if checkable.get("E0_compile") != "not_feasible":
        req: OrderedDict[str, Any] = OrderedDict([("runner", "cargo_build"), ("crate", crate_path)])
        if verification_model:
            req["verification_model"] = verification_model
        if classification in {"bounded_pointer", "state_mutating"}:
            req["raw_c2rust"] = c2rust_path
        reqs["E0_compile"] = req

    if checkable.get("E0_no_unsafe_marker") in {"required", "optional"}:
        reqs["E0_no_unsafe_marker"] = OrderedDict(
            [
                ("runner", "rustc_forbid_unsafe"),
                ("raw_candidate", raw_candidate or f"TODO: path/to/{function}_safe.rs"),
            ]
        )

    if checkable.get("E1_clippy") in {"required", "optional"}:
        reqs["E1_clippy"] = OrderedDict(
            [("runner", "clippy"), ("crate", crate_path), ("deny_warnings", True)]
        )

    if checkable.get("E2_test_suite") in {"required", "optional"}:
        reqs["E2_test_suite"] = OrderedDict(
            [("runner", "cargo_test"), ("crate", crate_path), ("test_filter", function)]
        )

    if checkable.get("E2_property_tests") in {"required", "optional"}:
        reqs["E2_property_tests"] = OrderedDict(
            [("runner", "cargo_test"), ("crate", crate_path), ("test_filter", function)]
        )

    if checkable.get("E3_miri_concrete_ub") in {"required", "optional"}:
        reqs["E3_miri_concrete_ub"] = OrderedDict(
            [("runner", "miri"), ("crate", crate_path), ("test_filter", function)]
        )

    for phase in ("E4_phase1_equivalence_to_c2rust", "E4_phase2_equivalence_to_spec"):
        if checkable.get(phase) not in {"required", "optional"}:
            continue
        harness_prefix = "equiv" if phase.endswith("c2rust") else "spec"
        req = OrderedDict(
            [
                ("runner", "kani"),
                ("crate", crate_path),
                ("harness", f"proofs::{harness_prefix}_{function}"),
                ("harness_file", harness_path),
                ("input_domain", domain),
            ]
        )
        if phase == "E4_phase2_equivalence_to_spec":
            req["spec"] = spec or f"TODO: specs/{function}.md"
        if classification in {"bounded_pointer", "state_mutating"}:
            req["kani_args"] = ["--default-unwind", "TODO: unwind-bound"]
            req["verification_model"] = verification_model or f"TODO: path/to/{function}_model.rs"
            req["raw_c2rust"] = c2rust_path
        reqs[phase] = req

    if checkable.get("E5_cross_tool") == "required":
        reqs["E5_cross_tool"] = OrderedDict(
            [
                ("runner", "evidence_fusion"),
                (
                    "inputs",
                    [
                        f"{function}.E4_phase2_equivalence_to_spec",
                        f"{function}.E3_miri_concrete_ub",
                    ],
                ),
            ]
        )

    return reqs


def _trust_skeleton(
    *,
    function: str,
    c_path: str,
    c2rust_path: str,
    classification: str,
    kind: str,
    domain: str,
) -> list[str]:
    trusted = [
        f"TODO: confirm {c_path} is the exact source artifact under study, including upstream commit/vendor pin if applicable",
        f"c2rust-transpile produced {c2rust_path} from {c_path} without semantic mistranslation of {function}",
        "TODO: confirm target C ABI type mappings used by this proof (for example c_int, size_t, int16_t, pointer width)",
    ]
    if kind == "bytes":
        trusted.extend(
            [
                "TODO: define and justify the bounded byte-buffer domain, including nullability, aliasing, and capacity assumptions",
                "TODO: confirm any libc/memory helper model is byte-equivalent on the declared bounded inputs",
            ]
        )
    elif kind == "pointer_struct":
        trusted.append(
            "TODO: define and justify the bounded pointer/struct domain, including pointee validity, aliasing, and mutation frame"
        )
    elif kind == "globals" or classification == "state_mutating":
        trusted.append(
            "TODO: confirm the verification model includes every global read/write relevant to this function"
        )
    elif classification == "ffi_or_event":
        trusted.append(
            "TODO: describe the external callback/FFI environment assumptions if this target is later modeled"
        )
    else:
        trusted.append(f"the symbolic input domain {domain} covers the full scalar input space intended by the plan")

    trusted.append("Kani's CBMC backend is sound for the operations exercised by the declared harnesses")
    return trusted


def _not_checkable(checkable: OrderedDict[str, str], artifact_mode: str, classification: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for level, status in checkable.items():
        if status != "not_feasible":
            continue
        reason = level
        rationale = "TODO: explain why this evidence gate is not feasible for this target"
        if level == "E0_no_unsafe_marker" and artifact_mode == "verbatim_model":
            reason = "absence of unsafe markers on the candidate"
            rationale = (
                "the skeleton is configured for a verbatim c2rust verification model; "
                "unsafe signatures and operations are intentionally preserved"
            )
        elif level == "E4_phase1_equivalence_to_c2rust" and artifact_mode == "verbatim_model":
            reason = "Phase 1 equivalence to the c2rust baseline"
            rationale = (
                "the verification model is intended to be copied from the c2rust output, "
                "so Phase 1 would be tautological unless a separate safe candidate is introduced"
            )
        elif classification == "ffi_or_event":
            reason = f"{level} for FFI/event target"
            rationale = "the triage classifier found event/FFI calls; a sound environment model is not present in this skeleton"
        items.append({"reason": reason, "rationale": rationale})
    return items


def _ceiling(checkable: OrderedDict[str, str]) -> str:
    required = [level for level, status in checkable.items() if status == "required"]
    if not required:
        return "E0"
    return max((plan_check.LEVEL_TO_CEILING[level] for level in required), key=lambda x: plan_check.CEILING_ORDER[x])


def build_plan(args: argparse.Namespace) -> OrderedDict[str, Any]:
    rust_path = Path(args.c2rust)
    rust_source = rust_path.read_text()
    analysis = _analyze_function(rust_path, args.function)
    if args.inventory:
        analysis = _apply_inventory(analysis, _read_inventory_row(Path(args.inventory), args.function))

    signature = _extract_plan_signature(analysis.header, args.function)
    kind = _derive_kind(analysis=analysis, signature=signature)
    domain = args.domain or _derive_domain(kind, signature, rust_source)

    c_source = Path(args.c_source) if args.c_source else None
    c_path = _repo_relative(c_source) if c_source else "TODO: path/to/source.c"
    c_line = _find_c_line(c_source, args.function, args.c_line)
    c2rust_path = _repo_relative(rust_path)

    side_effects = _detect_side_effects(analysis)
    determinism = _derive_determinism(analysis, side_effects)

    checkable = _default_checkable(analysis.classification, args.artifact_mode)
    _apply_required_overrides(checkable, args.require or [])

    tool_requirements = _tool_requirements(
        checkable=checkable,
        function=args.function,
        classification=analysis.classification,
        domain=domain,
        c2rust_path=c2rust_path,
        crate=_repo_relative(args.crate) if args.crate else None,
        harness_file=_repo_relative(args.harness_file) if args.harness_file else None,
        raw_candidate=_repo_relative(args.raw_candidate) if args.raw_candidate else None,
        spec=_repo_relative(args.spec) if args.spec else None,
        verification_model=_repo_relative(args.verification_model) if args.verification_model else None,
    )

    expected = OrderedDict(
        (level, _expected_for(level)) for level, status in checkable.items() if status == "required"
    )

    plan: OrderedDict[str, Any] = OrderedDict()
    plan["schema_version"] = 1
    plan["function"] = args.function
    plan["source"] = OrderedDict(
        [
            ("c", OrderedDict([("path", c_path), ("line", c_line)])),
            ("c2rust_unsafe", OrderedDict([("path", c2rust_path), ("line", analysis.start_line)])),
        ]
    )
    plan["input_signature"] = OrderedDict([("kind", kind), ("rust", signature), ("domain", domain)])
    plan["purity"] = OrderedDict([("side_effects", side_effects), ("determinism", determinism)])
    plan["spec_available"] = OrderedDict(
        [
            ("source", args.spec_source or "TODO: identify specification source, or set to none"),
            ("format", args.spec_format),
            ("excerpt", args.spec_excerpt or "TODO: write one or two sentences stating the intended contract"),
        ]
    )
    plan["checkable"] = checkable
    plan["tool_requirements"] = tool_requirements
    plan["trusted"] = _trust_skeleton(
        function=args.function,
        c_path=c_path,
        c2rust_path=c2rust_path,
        classification=analysis.classification,
        kind=kind,
        domain=domain,
    )
    plan["not_checkable"] = _not_checkable(checkable, args.artifact_mode, analysis.classification)
    plan["expected_outcomes"] = expected
    plan["ceiling"] = _ceiling(checkable)
    plan["notes"] = (
        f"Generated by tools/plan_skeleton.py from triage classification {analysis.classification} "
        f"(score={analysis.phase2_score}: {analysis.rationale}). Replace TODO fields before treating this as an authored plan."
    )
    return plan


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("c2rust", help="path to c2rust-transpile Rust output")
    ap.add_argument("--function", required=True)
    ap.add_argument("--out", help="output plan JSON; defaults to stdout")
    ap.add_argument("--force", action="store_true", help="overwrite an existing --out file")
    ap.add_argument("--inventory", help="optional triage_c2rust.py CSV to join for classification metadata")
    ap.add_argument("--c-source", help="original C source path")
    ap.add_argument("--c-line", type=int, help="override original C function line")
    ap.add_argument("--crate", help="verification crate path for cargo/Kani runners")
    ap.add_argument("--harness-file", help="proof harness file path")
    ap.add_argument("--raw-candidate", help="safe candidate file for E0_no_unsafe_marker")
    ap.add_argument("--verification-model", help="verification model file for pointer/state targets")
    ap.add_argument("--spec", help="specification file path for Phase 2")
    ap.add_argument("--spec-source", help="spec_available.source value")
    ap.add_argument(
        "--spec-format",
        choices=sorted(plan_check.SPEC_FORMATS),
        default="none",
        help="spec_available.format value",
    )
    ap.add_argument("--spec-excerpt", help="spec_available.excerpt value")
    ap.add_argument("--domain", help="override derived input_signature.domain")
    ap.add_argument(
        "--artifact-mode",
        choices=["safe_candidate", "verbatim_model"],
        default="safe_candidate",
        help="safe_candidate plans may compare a safe rewrite to c2rust; verbatim_model plans preserve c2rust and skip unsafe-marker/Phase-1 gates",
    )
    ap.add_argument(
        "--require",
        action="append",
        choices=LEVEL_CHOICES,
        default=[],
        help="mark an optional evidence level required; may be repeated",
    )
    args = ap.parse_args(argv)

    plan = build_plan(args)
    violations = plan_check.validate(plan, args.out or "<stdout>", stage="pre")
    if violations:
        for violation in violations:
            print(f"[plan_skeleton] internal validation error: {violation}", file=sys.stderr)
        return 2

    text = json.dumps(plan, indent=2) + "\n"
    if args.out:
        out_path = Path(args.out)
        if out_path.exists() and not args.force:
            print(f"{out_path} exists; pass --force to overwrite", file=sys.stderr)
            return 1
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text)
        print(f"[+] wrote {out_path}")
        print("[+] pre-stage validation passed")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
