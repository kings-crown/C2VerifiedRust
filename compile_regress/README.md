# C2Rust regression checks

These seven fixtures exercise the local C2Rust fork's literal, integer-promotion,
and overflow patches:

| Fixtures | Check |
| --- | --- |
| `offt_minus.c`, `shift_width.c`, `unsigned_sub.c`, `literal_narrow.c`, `varargs.c` | Transpile, then compile the generated Rust with stable Rust. |
| `overflow_runtime.c` | Compare C and Rust results for add/subtract/multiply overflow builtins, including narrow operands with wider outputs and boundary flags/results. |
| `unary_promotions_runtime.c` | Compare C and Rust results for unary `+`, `-`, `~`, and the promoted result widths. |

The two runtime fixtures use `nightly-2023-04-15`, matching upstream snapshot
tests. Address-taking in generated code can emit `#![feature(raw_ref_op)]`.
The original five fixtures check compilation only; they are not runtime
equivalence tests. Overflow coverage is limited to the cases in the fixture;
it does not establish correctness for every operand/output type combination.
Mixed signedness and narrowing output types remain known limitations of the
existing overflow patch.

## 1) Select the build tools

The local build uses the complete LLVM 18 development installation, including
`libclangBasic.a`. On Debian/Ubuntu, the relevant packages are `clang-18`,
`clang-tools-18`, `llvm-18-dev`, and `libclang-18-dev`.

```bash
export PATH="$HOME/.cargo/bin:/usr/lib/llvm-18/bin:$PATH"
export LLVM_CONFIG_PATH=/usr/lib/llvm-18/bin/llvm-config
export CLANG_PATH=/usr/lib/llvm-18/bin/clang
export LIBCLANG_PATH=/usr/lib/llvm-18/lib
export CARGO_TARGET_DIR=/tmp/c2rust-upgrade-llvm18-target

rustup toolchain install nightly-2023-04-15 --profile minimal
```

Use `cargo +stable` to build the transpiler. The fork's workspace default nightly
is for its older compiler-internals tooling.

## 2) Copy the project regressions into the fork

The harness stored here is an integration test for the sibling C2Rust crate;
this project's `c2rust-transpile/` directory is not a standalone Cargo package.

```bash
cd /home/brao/Desktop/c2rust
mkdir -p c2rust-transpile/tests/compile_regress
cp ../C2VerifiedRust/c2rust-transpile/tests/compile_regress.rs \
   c2rust-transpile/tests/
cp ../C2VerifiedRust/compile_regress/*.c \
   c2rust-transpile/tests/compile_regress/
```

## 3) Build and run the tests

```bash
cargo +stable build --locked --release -p c2rust --bins
cargo +stable test --locked --release \
  -p c2rust-transpile --test compile_regress -- --nocapture

# Also run the upstream transpiler package tests.
cargo +stable test --locked --release -p c2rust-transpile
```

The regression harness copies each C fixture into a temporary directory and
keeps generated Rust, compile databases, libraries, and executables there. It
removes those files on success or failure. Cargo build output stays under the
`CARGO_TARGET_DIR` in `/tmp`.

These commands test the checked-out source. After successful validation, install
both command-line executables from the same checkout:

```bash
cargo +stable install --locked --force --path c2rust
hash -r
c2rust --version
c2rust-transpile --version
git rev-parse HEAD
```

One install command installs both `c2rust` and `c2rust-transpile`. Record the full
fork revision with the Rust and LLVM versions in the project README; the package
version alone does not identify the local patches.
The current tested revision and remaining dependency warnings are recorded in
[the project README](../README.md#run-verification).

## Optional: end-to-end `tail` pipeline

Using whichever binary is on PATH:

```bash
cd /home/brao/Desktop/C2VerifiedRust/c2rust_baseline
python3 create_c_and_rust_versions.py \
  --program_name tail \
  --coreutils_dir "$COREUTILS_SRC" \
  --corpus_dir "$CORPUS_DIR"

./run_c2r_tests.sh tail
```

This rebuilds C and Rust for `tail` and runs the curated test subset. Set `COREUTILS_SRC` and `CORPUS_DIR` as described in [the baseline walkthrough](../c2rust_baseline/README.md).
