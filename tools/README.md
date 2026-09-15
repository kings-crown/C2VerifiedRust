# Verification workflow tools

```text
Baseline inventory -> verification plan -> runner evidence -> reconciliation -> repair input
```

Commands below use an illustrative local target under `generated/target/`.
Supply its C source, generate its C2Rust baseline, and create a candidate and
proof crate for your function. Target artifacts and run output are ignored by
Git. The workflow tools use Python's standard library.

## Inventory and plan

After generating `baseline.rs`, collect an inventory and derive a plan:

```bash
python3 tools/triage_c2rust.py generated/target/baseline.rs \
  --out generated/target/inventory.csv

python3 tools/plan_skeleton.py generated/target/baseline.rs \
  --function target_function \
  --c-source generated/target/source.c \
  --inventory generated/target/inventory.csv \
  --artifact-mode verbatim_model \
  --require E4_phase2_equivalence_to_spec \
  --out generated/target/plan.json
```

Complete the generated plan's TODOs, specification, trust assumptions,
expected outcomes, candidate path, and proof-crate/harness configuration.
See the [schema](../plans/SCHEMA.md).

`plan_check.py` validates the plan without running verifiers. `pre` checks
its structure; `ready` also requires the configured artifacts to exist:

```bash
python3 tools/plan_check.py --stage pre generated/target/plan.json
python3 tools/plan_check.py --stage ready generated/target/plan.json
```

## Verify and reconcile

The orchestrator runs the checks declared by the plan:

```bash
python3 tools/verify_function.py \
  --plan generated/target/plan.json \
  --run-id candidate-check
```

It writes:

```text
runs/candidate-check/
  plan.json
  evidence/
  evidence.json
  reconciliation.json
  logs/
```

Individual runners can also produce normalized evidence:

```bash
python3 tools/run_rustc.py --plan generated/target/plan.json \
  --out runs/manual/evidence/E0_compile.json
python3 tools/check_no_unsafe_marker.py generated/target/candidate \
  --out runs/manual/unsafe_marker_summary.json \
  --evidence-out runs/manual/evidence/E0_no_unsafe_marker.json
python3 tools/run_kani.py --plan generated/target/plan.json \
  --property-key E4_phase2_equivalence_to_spec \
  --out runs/manual/evidence/E4_phase2.json
```

The unsafe-marker runner expects files named `<function>_safe.rs` in the
candidate directory. `run_clippy.py` and `run_miri.py` provide lint and
concrete undefined-behavior checks; `fuse_evidence.py` can combine compatible
normalized findings. Configure the required external tools for each check.

Reconcile a plan with evidence from a run:

```bash
python3 tools/reconcile.py --plan runs/candidate-check/plan.json \
  --evidence runs/candidate-check/evidence.json \
  --out runs/candidate-check/reconciliation.json
```

## Prepare repair input

`repair_from_diagnostics.py` packages the first failing finding as a bounded
repair prompt:

```bash
python3 tools/repair_from_diagnostics.py \
  --plan runs/candidate-check/plan.json \
  --evidence runs/candidate-check/evidence.json \
  --out runs/candidate-check/repair_prompt.md
```

Apply a repair to the candidate, then verify it in a new run directory.
