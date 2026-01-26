set -euo pipefail

# Generic test runner: for each program, build C and Rust, find tests in
# c2saferrust/coreutils/tests/<prog>, select the ones that pass on C, then run
# that subset on Rust. Uses bash to satisfy test harness expectations.
#
# Usage: ./run_cat_tests.sh [prog1 [prog2 ...]]
# If no programs are provided, it will run all translated programs found
# under $CORPUS_DIR (each subdirectory with both c/ and rust/).
#
# Env overrides:
#   REPO_ROOT    - repo root (default: parent of this script)
#   COREUTILS_SRC- coreutils source dir (default: /tmp/coreutils)
#   CORPUS_DIR   - corpus output dir containing <prog>/{c,rust} (default: /tmp/c2rust_corpus/coreutils)
#   TEST_ROOT    - root of tests (default: $REPO_ROOT/c2saferrust/coreutils/tests)
#   PATH_PREFIX  - PATH additions (default: "$REPO_ROOT/c2saferrust/coreutils/getlimits:$HOME/.cargo/bin:/usr/lib/llvm-15/bin")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
COREUTILS_SRC="${COREUTILS_SRC:-/tmp/coreutils}"
CORPUS_DIR="${CORPUS_DIR:-/tmp/c2rust_corpus/coreutils}"
TEST_ROOT="${TEST_ROOT:-$REPO_ROOT/c2saferrust/coreutils/tests}"
# Prepend helper tool directories so tests can find binaries like `getlimits`.
PATH_PREFIX="${PATH_PREFIX:-$REPO_ROOT/c2saferrust/coreutils/getlimits:$HOME/.cargo/bin:/usr/lib/llvm-15/bin}"
# Provide a sane default for AWK, which some tests require (e.g., retry_delay_).
AWK="${AWK:-awk}"
export AWK

PROGRAMS=("$@")
if [[ ${#PROGRAMS[@]} -eq 0 ]]; then
  if [[ -d "$CORPUS_DIR" ]]; then
    # Discover program directories that have both C and Rust outputs.
    mapfile -t PROGRAMS < <(find "$CORPUS_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | LC_ALL=C sort)
  fi
  if [[ ${#PROGRAMS[@]} -eq 0 ]]; then
    echo "No program directories found under $CORPUS_DIR"
    exit 1
  fi
fi

echo "Repo root:    $REPO_ROOT"
echo "Coreutils:    $COREUTILS_SRC"
echo "Corpus dir:   $CORPUS_DIR"
echo "Test root:    $TEST_ROOT"
echo "PATH prefix:  $PATH_PREFIX"
echo

overall_rc=0

for prog in "${PROGRAMS[@]}"; do
  echo "=== Program: $prog ==="
  C_DIR="$CORPUS_DIR/$prog/c"
  RUST_DIR="$CORPUS_DIR/$prog/rust"
  TEST_DIR="$TEST_ROOT/$prog"
  C_BIN_DIR="$C_DIR"
  RUST_BIN_DIR="$RUST_DIR/target/debug"

  if [[ ! -d "$C_DIR" || ! -d "$RUST_DIR" ]]; then
    echo "  Skipping $prog: missing c/ or rust/ under $C_DIR / $RUST_DIR"
    overall_rc=1
    continue
  fi

  if [[ ! -d "$TEST_DIR" ]]; then
    echo "  Tests not found: $TEST_DIR (skipping $prog)"
    overall_rc=1
    continue
  fi

  echo "  Building C..."
  (cd "$C_DIR" && make && ar rcs lib${prog}deps.a *.o) >/tmp/${prog}_c_build.log 2>&1 || {
    echo "  C build failed (see /tmp/${prog}_c_build.log)"
    overall_rc=1
    continue
  }
  if [[ ! -x "$C_BIN_DIR/$prog" ]]; then
    echo "  C binary missing: $C_BIN_DIR/$prog"
    overall_rc=1
    continue
  fi

  echo "  Building Rust..."
  # Allow caller to inject extra RUSTFLAGS (e.g., to add link args) via env.
  (cd "$RUST_DIR" && PATH="$PATH_PREFIX:$PATH" RUSTFLAGS="${RUSTFLAGS:-}" cargo build) >/tmp/${prog}_rust_build.log 2>&1 || {
    echo "  Rust build failed (see /tmp/${prog}_rust_build.log)"
    overall_rc=1
    continue
  }
  if [[ ! -x "$RUST_BIN_DIR/$prog" ]]; then
    echo "  Rust binary missing: $RUST_BIN_DIR/$prog"
    overall_rc=1
    continue
  fi

  echo "  Selecting tests that pass on C..."
  PASSING=()
  for t in "$TEST_DIR"/*.sh; do
    [[ -x "$t" ]] || continue
    if PATH="$PATH_PREFIX:$PATH" bash "$t" "$C_BIN_DIR" >/tmp/${prog}_c_test.log 2>&1; then
      PASSING+=("$t")
      echo "    [PASS] $(basename "$t")"
    else
      echo "    [FAIL] $(basename "$t") (ignored for Rust run)"
    fi
  done

  if [[ ${#PASSING[@]} -eq 0 ]]; then
    echo "  No passing tests on C; skipping Rust run."
    overall_rc=1
    continue
  fi

  echo "  Running passing tests on Rust..."
  rust_fail=0
  for t in "${PASSING[@]}"; do
    if PATH="$PATH_PREFIX:$PATH" bash "$t" "$RUST_BIN_DIR" >/tmp/${prog}_rust_test.log 2>&1; then
      echo "    [PASS] $(basename "$t")"
    else
      echo "    [FAIL] $(basename "$t")"
      rust_fail=1
    fi
  done

  if [[ $rust_fail -eq 0 ]]; then
    echo "  All selected tests passed on Rust for $prog."
  else
    echo "  Some selected tests failed on Rust for $prog (see /tmp/${prog}_rust_test.log)."
    overall_rc=1
  fi
  echo
done

exit $overall_rc
