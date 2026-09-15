"""Validate a Verification Plan against the schema in plans/SCHEMA.md.

Exits 0 if every plan passes, 1 if any plan fails. Prints a list of
violations per plan.

Usage:
    python3 tools/plan_check.py --stage pre plans/c_isalpha.json
    python3 tools/plan_check.py --stage ready plans/*.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]


VALID_LEVEL_IDS = {
    "E0_compile",
    "E0_no_unsafe_marker",
    "E1_clippy",
    "E2_test_suite",
    "E2_property_tests",
    "E3_miri_concrete_ub",
    "E4_phase1_equivalence_to_c2rust",
    "E4_phase2_equivalence_to_spec",
    "E5_cross_tool",
}

CHECKABLE_VALUES = {"required", "optional", "not_feasible"}

CEILING_ORDER = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "E4": 4, "E5": 5}

LEVEL_TO_CEILING = {
    "E0_compile": "E0",
    "E0_no_unsafe_marker": "E0",
    "E1_clippy": "E1",
    "E2_test_suite": "E2",
    "E2_property_tests": "E2",
    "E3_miri_concrete_ub": "E3",
    "E4_phase1_equivalence_to_c2rust": "E4",
    "E4_phase2_equivalence_to_spec": "E4",
    "E5_cross_tool": "E5",
}

E0_OUTCOMES = {"PASS", "FAIL"}
E4_STATUSES = {"SUCCESS", "FAILURE", "UNKNOWN"}
E4_COVERS = {"ALL_SATISFIED", "SOME_UNSATISFIABLE", "NOT_REQUIRED"}
E5_OUTCOMES = {"AGREES", "DISAGREES", "NOT_RUN"}

RUNNERS = {
    "E0_compile": {"cargo_build"},
    "E0_no_unsafe_marker": {"rustc_forbid_unsafe"},
    "E1_clippy": {"clippy"},
    "E2_test_suite": {"cargo_test", "pytest"},
    "E2_property_tests": {"proptest", "quickcheck", "cargo_test"},
    "E3_miri_concrete_ub": {"miri"},
    "E4_phase1_equivalence_to_c2rust": {"kani"},
    "E4_phase2_equivalence_to_spec": {"kani"},
    "E5_cross_tool": {"evidence_fusion"},
}

SIGNATURE_KINDS = {"scalar", "scalar_list", "bytes", "pointer_struct", "varargs", "globals"}
SIDE_EFFECTS = {
    "none",
    "reads_globals",
    "writes_globals",
    "writes_output_buffer",
    "syscalls",
    "allocates",
}
DETERMINISM = {"total", "partial", "nondeterministic"}
SPEC_FORMATS = {"documented_contract", "iso_c", "none"}


def _repo_path(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO / p


def _require(violations: list[str], obj: dict, path: str, key: str, ty: type) -> Any:
    if key not in obj:
        violations.append(f"{path}: missing required field '{key}'")
        return None
    val = obj[key]
    if not isinstance(val, ty):
        violations.append(f"{path}.{key}: expected {ty.__name__}, got {type(val).__name__}")
        return None
    return val


def _check_e0_outcome(violations: list[str], path: str, val: Any) -> None:
    if val not in E0_OUTCOMES:
        violations.append(f"{path}: must be one of {sorted(E0_OUTCOMES)}, got {val!r}")


def _check_e4_outcome(violations: list[str], path: str, val: Any) -> None:
    if not isinstance(val, dict):
        violations.append(f"{path}: must be an object with status+covers, got {type(val).__name__}")
        return
    status = val.get("status")
    if status not in E4_STATUSES:
        violations.append(f"{path}.status: must be one of {sorted(E4_STATUSES)}, got {status!r}")
    covers = val.get("covers")
    if covers not in E4_COVERS:
        violations.append(f"{path}.covers: must be one of {sorted(E4_COVERS)}, got {covers!r}")


def _check_e5_outcome(violations: list[str], path: str, val: Any) -> None:
    if val not in E5_OUTCOMES:
        violations.append(f"{path}: must be one of {sorted(E5_OUTCOMES)}, got {val!r}")


def _check_outcome(violations: list[str], level_id: str, path: str, val: Any) -> None:
    if level_id.startswith("E0"):
        _check_e0_outcome(violations, path, val)
    elif level_id in {"E1_clippy", "E2_test_suite", "E2_property_tests", "E3_miri_concrete_ub"}:
        _check_e0_outcome(violations, path, val)
    elif level_id.startswith("E4"):
        _check_e4_outcome(violations, path, val)
    elif level_id == "E5_cross_tool":
        _check_e5_outcome(violations, path, val)


def _check_tool_requirement_shape(
    violations: list[str],
    plan_path: str,
    level_id: str,
    req: Any,
) -> None:
    path = f"{plan_path}.tool_requirements.{level_id}"
    if not isinstance(req, dict):
        violations.append(f"{path}: must be object")
        return
    runner = req.get("runner")
    if runner not in RUNNERS.get(level_id, set()):
        violations.append(
            f"{path}.runner: must be one of {sorted(RUNNERS.get(level_id, []))}, got {runner!r}"
        )

    if level_id in {"E0_compile", "E1_clippy", "E2_test_suite", "E2_property_tests", "E3_miri_concrete_ub"}:
        if not isinstance(req.get("crate"), str):
            violations.append(f"{path}.crate: required string for runner {runner!r}")
    elif level_id == "E0_no_unsafe_marker":
        if not isinstance(req.get("raw_candidate"), str):
            violations.append(f"{path}.raw_candidate: required string")
    elif level_id.startswith("E4"):
        if not isinstance(req.get("crate"), str):
            violations.append(f"{path}.crate: required string")
        if not isinstance(req.get("harness"), str):
            violations.append(f"{path}.harness: required string")
        if level_id == "E4_phase2_equivalence_to_spec" and not isinstance(req.get("spec"), str):
            violations.append(f"{path}.spec: required string for Phase 2")
        kani_args = req.get("kani_args", [])
        if not isinstance(kani_args, list) or not all(isinstance(arg, str) for arg in kani_args):
            violations.append(f"{path}.kani_args: optional list of strings")
    elif level_id == "E5_cross_tool":
        inputs = req.get("inputs")
        if not isinstance(inputs, list) or len(inputs) < 2:
            violations.append(f"{path}.inputs: must name at least two underlying property ids")


def _check_ready_artifacts(
    violations: list[str],
    plan_path: str,
    level_id: str,
    req: dict,
) -> None:
    path = f"{plan_path}.tool_requirements.{level_id}"
    if level_id in {"E0_compile", "E1_clippy", "E2_test_suite", "E2_property_tests", "E3_miri_concrete_ub"}:
        crate = _repo_path(req.get("crate", ""))
        if not (crate / "Cargo.toml").exists():
            violations.append(f"{path}.crate: missing Cargo.toml at {crate / 'Cargo.toml'}")
    elif level_id == "E0_no_unsafe_marker":
        raw = _repo_path(req.get("raw_candidate", ""))
        if not raw.exists():
            violations.append(f"{path}.raw_candidate: missing file {raw}")
    elif level_id.startswith("E4"):
        crate = _repo_path(req.get("crate", ""))
        if not (crate / "Cargo.toml").exists():
            violations.append(f"{path}.crate: missing Cargo.toml at {crate / 'Cargo.toml'}")
        harness_file = req.get("harness_file")
        if harness_file and not _repo_path(harness_file).exists():
            violations.append(f"{path}.harness_file: missing file {_repo_path(harness_file)}")
        if level_id == "E4_phase2_equivalence_to_spec":
            spec = _repo_path(req.get("spec", ""))
            if not spec.exists():
                violations.append(f"{path}.spec: missing file {spec}")


def validate(plan: dict, plan_path: str, stage: str = "pre") -> list[str]:
    violations: list[str] = []

    sv = _require(violations, plan, plan_path, "schema_version", int)
    if sv is not None and sv != 1:
        violations.append(f"{plan_path}.schema_version: must be 1, got {sv}")

    _require(violations, plan, plan_path, "function", str)

    src = _require(violations, plan, plan_path, "source", dict) or {}
    src_c = src.get("c", {})
    if not isinstance(src_c, dict) or not src_c.get("path") or not isinstance(src_c.get("line"), int):
        violations.append(f"{plan_path}.source.c: must have path (str) and line (int)")
    src_r = src.get("c2rust_unsafe", {})
    if not isinstance(src_r, dict) or not src_r.get("path") or not isinstance(src_r.get("line"), int):
        violations.append(f"{plan_path}.source.c2rust_unsafe: must have path (str) and line (int)")

    sig = _require(violations, plan, plan_path, "input_signature", dict) or {}
    if sig.get("kind") not in SIGNATURE_KINDS:
        violations.append(f"{plan_path}.input_signature.kind: must be one of {sorted(SIGNATURE_KINDS)}")
    if not isinstance(sig.get("rust"), str):
        violations.append(f"{plan_path}.input_signature.rust: must be string")
    if not isinstance(sig.get("domain"), str):
        violations.append(f"{plan_path}.input_signature.domain: must be string")

    pur = _require(violations, plan, plan_path, "purity", dict) or {}
    if pur.get("side_effects") not in SIDE_EFFECTS:
        violations.append(f"{plan_path}.purity.side_effects: must be one of {sorted(SIDE_EFFECTS)}")
    if pur.get("determinism") not in DETERMINISM:
        violations.append(f"{plan_path}.purity.determinism: must be one of {sorted(DETERMINISM)}")

    spec = _require(violations, plan, plan_path, "spec_available", dict) or {}
    if not isinstance(spec.get("source"), str):
        violations.append(f"{plan_path}.spec_available.source: must be string")
    if spec.get("format") not in SPEC_FORMATS:
        violations.append(f"{plan_path}.spec_available.format: must be one of {sorted(SPEC_FORMATS)}")
    if not isinstance(spec.get("excerpt"), str):
        violations.append(f"{plan_path}.spec_available.excerpt: must be string")

    checkable = _require(violations, plan, plan_path, "checkable", dict) or {}
    for k, v in checkable.items():
        if k not in VALID_LEVEL_IDS:
            violations.append(f"{plan_path}.checkable: unknown level id {k!r}; valid ids: {sorted(VALID_LEVEL_IDS)}")
        if v not in CHECKABLE_VALUES:
            violations.append(f"{plan_path}.checkable.{k}: must be one of {sorted(CHECKABLE_VALUES)}, got {v!r}")

    trusted = _require(violations, plan, plan_path, "trusted", list) or []
    if not trusted:
        violations.append(f"{plan_path}.trusted: must be non-empty (a plan with no trust assumptions is dishonest)")
    for i, t in enumerate(trusted):
        if not isinstance(t, str):
            violations.append(f"{plan_path}.trusted[{i}]: must be string")

    nc = plan.get("not_checkable", [])
    if not isinstance(nc, list):
        violations.append(f"{plan_path}.not_checkable: must be list")
    else:
        for i, item in enumerate(nc):
            if not isinstance(item, dict) or not item.get("reason") or not item.get("rationale"):
                violations.append(f"{plan_path}.not_checkable[{i}]: must have both reason and rationale")

    expected = _require(violations, plan, plan_path, "expected_outcomes", dict) or {}
    required_levels = {k for k, v in checkable.items() if v == "required"}
    for k in required_levels:
        if k not in expected:
            violations.append(f"{plan_path}.expected_outcomes: missing entry for required check {k!r}")
    for k, v in expected.items():
        if k not in checkable:
            violations.append(f"{plan_path}.expected_outcomes.{k}: not declared in checkable")
        else:
            _check_outcome(violations, k, f"{plan_path}.expected_outcomes.{k}", v)

    tool_requirements = plan.get("tool_requirements", {})
    if not isinstance(tool_requirements, dict):
        violations.append(f"{plan_path}.tool_requirements: must be object")
        tool_requirements = {}
    for k in required_levels:
        if k not in tool_requirements:
            violations.append(f"{plan_path}.tool_requirements: missing entry for required check {k!r}")
    for k, req in tool_requirements.items():
        if k not in checkable:
            violations.append(f"{plan_path}.tool_requirements.{k}: not declared in checkable")
            continue
        if checkable.get(k) == "not_feasible":
            violations.append(f"{plan_path}.tool_requirements.{k}: check is not_feasible and should not have a runner")
            continue
        _check_tool_requirement_shape(violations, plan_path, k, req)
        if stage == "ready" and isinstance(req, dict):
            _check_ready_artifacts(violations, plan_path, k, req)

    ceiling = _require(violations, plan, plan_path, "ceiling", str)
    if ceiling and ceiling not in CEILING_ORDER:
        violations.append(f"{plan_path}.ceiling: must be one of E0..E5, got {ceiling!r}")
    elif ceiling and required_levels:
        max_required = max(CEILING_ORDER[LEVEL_TO_CEILING[k]] for k in required_levels)
        if CEILING_ORDER[ceiling] < max_required:
            violations.append(
                f"{plan_path}.ceiling: {ceiling} is below the highest required check "
                f"({sorted(LEVEL_TO_CEILING[k] for k in required_levels)})"
            )

    return violations


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["pre", "ready"], default="pre")
    ap.add_argument("plans", nargs="+")
    args = ap.parse_args(argv[1:])

    total_violations = 0
    for arg in args.plans:
        path = Path(arg)
        try:
            plan = json.loads(path.read_text())
        except Exception as e:
            print(f"[FAIL] {path}: cannot parse JSON: {e}")
            total_violations += 1
            continue

        violations = validate(plan, str(path), stage=args.stage)
        if violations:
            print(f"[FAIL] {path}")
            for v in violations:
                print(f"  - {v}")
            total_violations += len(violations)
        else:
            print(
                f"[ OK ] {path}: function={plan.get('function')}, "
                f"ceiling={plan.get('ceiling')}, trusted={len(plan.get('trusted', []))}, "
                f"stage={args.stage}"
            )

    return 0 if total_violations == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
