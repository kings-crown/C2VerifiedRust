"""Plan-driven verification orchestrator.

This is the HCSS control loop in executable form:

  plan_check(pre) -> plan_check(ready) -> run declared gates -> merge evidence
  -> reconcile plan vs evidence.

It does not generate or edit Rust yet; the translation/repair loop can call
this command after producing a candidate.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import plan_check
from evidence import REPO, default_run_id, merge_documents, read_json, write_json


TOOLS = Path(__file__).resolve().parent


def _script(name: str) -> str:
    return str(TOOLS / name)


def _run(cmd: list[str]) -> int:
    print("[run]", " ".join(cmd))
    result = subprocess.run(cmd, cwd=REPO)
    return result.returncode


def _check_plan(plan: dict, plan_path: Path, stage: str) -> None:
    violations = plan_check.validate(plan, str(plan_path), stage=stage)
    if violations:
        for violation in violations:
            print(f"[plan:{stage}] {violation}", file=sys.stderr)
        raise SystemExit(2)


def _runner_for(
    *,
    key: str,
    plan_path: Path,
    plan: dict,
    run_id: str,
    out_path: Path,
    run_dir: Path,
    use_existing_kani: bool,
) -> list[str] | None:
    req = plan.get("tool_requirements", {}).get(key, {})
    py = sys.executable

    if key == "E0_compile":
        return [py, _script("run_rustc.py"), "--plan", str(plan_path), "--out", str(out_path), "--run-id", run_id]

    if key == "E0_no_unsafe_marker":
        raw = REPO / req["raw_candidate"]
        legacy = run_dir / "legacy_e0_no_unsafe_marker.json"
        return [
            py,
            _script("check_no_unsafe_marker.py"),
            str(raw.parent),
            "--out",
            str(legacy),
            "--evidence-out",
            str(out_path),
            "--run-id",
            run_id,
            "--fail-on-failures",
        ]

    if key == "E1_clippy":
        return [py, _script("run_clippy.py"), "--plan", str(plan_path), "--out", str(out_path), "--run-id", run_id]

    if key == "E3_miri_concrete_ub":
        return [py, _script("run_miri.py"), "--plan", str(plan_path), "--out", str(out_path), "--run-id", run_id]

    if key.startswith("E4"):
        cmd = [
            py,
            _script("run_kani.py"),
            "--plan",
            str(plan_path),
            "--property-key",
            key,
            "--out",
            str(out_path),
            "--run-id",
            run_id,
            "--log",
            str(run_dir / "logs" / f"{key}.log"),
        ]
        legacy = req.get("legacy_evidence")
        if use_existing_kani and legacy:
            cmd.extend(["--use-existing", legacy])
        return cmd

    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--run-id")
    ap.add_argument("--include-optional", action="store_true")
    ap.add_argument(
        "--use-existing-kani",
        action="store_true",
        help="Import legacy Kani evidence named in the plan instead of running cargo kani",
    )
    args = ap.parse_args(argv)

    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = REPO / plan_path
    plan = read_json(plan_path)

    _check_plan(plan, plan_path, "pre")
    _check_plan(plan, plan_path, "ready")

    run_id = args.run_id or default_run_id(plan["function"])
    run_dir = REPO / args.runs_dir / run_id
    evidence_dir = run_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(exist_ok=True)
    shutil.copyfile(plan_path, run_dir / "plan.json")

    runnable = []
    for key, status in plan["checkable"].items():
        if status == "required" or (args.include_optional and status == "optional"):
            runnable.append(key)

    runner_outputs: list[Path] = []
    runner_failures: dict[str, int] = {}
    for key in runnable:
        out_path = evidence_dir / f"{key}.json"
        cmd = _runner_for(
            key=key,
            plan_path=plan_path,
            plan=plan,
            run_id=run_id,
            out_path=out_path,
            run_dir=run_dir,
            use_existing_kani=args.use_existing_kani,
        )
        if cmd is None:
            print(f"[skip] no runner implemented for {key}")
            continue
        rc = _run(cmd)
        if out_path.exists():
            runner_outputs.append(out_path)
        if rc != 0:
            runner_failures[key] = rc

    docs = [read_json(p) for p in runner_outputs]
    aggregate = merge_documents(run_id=run_id, documents=docs, tool="verify_function")
    aggregate["run"]["metadata"]["runner_failures"] = runner_failures
    aggregate_path = run_dir / "evidence.json"
    write_json(aggregate_path, aggregate)

    reconcile_path = run_dir / "reconciliation.json"
    rc = _run(
        [
            sys.executable,
            _script("reconcile.py"),
            "--plan",
            str(run_dir / "plan.json"),
            "--evidence",
            str(aggregate_path),
            "--out",
            str(reconcile_path),
        ]
    )
    print(f"[+] run dir: {run_dir}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
