# C→Rust Mechanical Translation Walkthrough (C2Rust + Helpers)

This guide shows how to translate a Coreutils program (e.g., cat) from C to Rust with the provided scripts, automatically link the Rust crate to the original C helper objects, and run the Coreutils tests.

## 0) Prerequisites
- Linux with `git`, `gcc`, `make`, `python3`, `perl`, `cmake`-style build basics.
- Packages for Coreutils bootstrap: `autopoint`, `gettext`, `gperf`, `texinfo`, `texlive`, `texlive-latex-base`.
- Clang tools for `intercept-build`: `clang-tools-15` (provides `intercept-build` at `/usr/lib/llvm-15/bin`).
- Rust toolchain via rustup (stable) and `c2rust` installed via cargo.

### Install the key tools (Debian/Ubuntu style)
```sh
sudo apt-get update
sudo apt-get install -y \
  git build-essential autopoint gettext gperf texinfo texlive texlive-latex-base \
  clang-tools-15

# Install rustup + stable toolchain (if not already)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup default stable

# Install c2rust
export PATH="$HOME/.cargo/bin:$PATH"
cargo install c2rust --force
```

### PATH you need for every run
```sh
export PATH="$HOME/.cargo/bin:/usr/lib/llvm-15/bin:$PATH"
```

### Get the c2saferrust repository (for tests, slicer, attribution)
This project depends on the upstream c2saferrust code and tests from Vikram Nitin et al. Clone it:
```sh
git clone https://github.com/vikramnitin9/c2saferrust
```
Tests and tooling referenced here come from that project; please attribute the authors per their repository.


## 1) Fetch and build coreutils (once)
```sh
export REPO_ROOT=~/C2VerifiedRust                       # change to your clone path
export COREUTILS_SRC=/tmp/coreutils                     # where coreutils will be cloned/built
export CORPUS_DIR="$REPO_ROOT/translated_coreutils"     # where translated C/Rust will be written

bash "$REPO_ROOT/c2rust_baseline/download_coreutils.sh"
```
This clones to `$COREUTILS_SRC`, runs `bootstrap`, `configure`, and `make`.

## 2) Run the translator for one program (example: `cat`)
```sh
python3 c2rust_baseline/create_c_and_rust_versions.py \
  --program_name cat \
  --coreutils_dir "$COREUTILS_SRC" \
  --corpus_dir "$CORPUS_DIR"
```
What happens:
- Copies C sources/deps to `$CORPUS_DIR/cat/c` and builds them.
- Uses `intercept-build` to capture `compile_commands.json`.
- Runs `c2rust transpile` to produce a Rust crate at `$CORPUS_DIR/cat/rust`.
- Runs `cargo fix` inside that crate.
- Builds the C archive (`libcatdeps.a`) and writes `build.rs`/`Cargo.toml` so the Rust crate links the C helpers and extra libs automatically, then runs `cargo build`.

## 3) Link wiring (auto-generated)
The translator now writes `build.rs` and updates `Cargo.toml` to link the C archive and libs. If you need to regenerate manually, the expected `build.rs` is:
```rust
use std::env;
use std::path::PathBuf;

fn main() {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let c_dir = manifest_dir.parent().unwrap().join("c");

    println!("cargo:rustc-link-search=native={}", c_dir.display());
    println!("cargo:rustc-link-lib=static=catdeps");
    println!("cargo:rustc-link-lib=crypto");
    println!("cargo:rustc-link-lib=ssl");
    println!("cargo:rustc-link-lib=gmp");
    // Also emit raw link args to force the flags through on some toolchains.
    println!("cargo:rustc-link-arg=-L{}", c_dir.display());
    println!("cargo:rustc-link-arg=-lcatdeps");
    println!("cargo:rustc-link-arg=-lcrypto");
    println!("cargo:rustc-link-arg=-lssl");
    println!("cargo:rustc-link-arg=-lgmp");
}
```
Also ensure `Cargo.toml` has `build = "build.rs"` so the script runs.

This adds the C archive path, links `libcatdeps.a`, and brings in the extra libs the C Makefile used (`-lcrypto -lssl -lgmp`).

## 4) Build the Rust crate (if you want to re-run manually)
```sh
cd "$CORPUS_DIR/cat/rust"
PATH="$HOME/.cargo/bin:/usr/lib/llvm-15/bin:$PATH" cargo build
```
If it links cleanly, you have a working translated binary in `target/debug/cat`. If you see missing-symbol errors for gnulib helpers, re-run `make && ar rcs libcatdeps.a *.o` in `$CORPUS_DIR/cat/c` (the translator regenerates the C dir) and rebuild.

## 5) Run coreutils tests via the harness
Use the generic runner to select C-passing tests and rerun on Rust:
```sh
cd "$REPO_ROOT/c2rust_baseline"
PATH="$HOME/.cargo/bin:/usr/lib/llvm-15/bin:$PATH" \
./run_c2r_tests.sh cat
```
- The script builds both C/Rust, runs all `c2saferrust/coreutils/tests/cat/*.sh` on C, then only the passing ones on Rust.
- If a test (e.g., `cat-buf.sh`) fails on the C baseline, it is skipped for Rust. To make it pass, use a full coreutils build or adjust buffering in the extracted C.

For multiple programs, list them: `./run_c2r_tests.sh cat head tail` (after each is generated into `$CORPUS_DIR/<prog>`).

## Notes and repeats
- Re-run step 3 whenever you re-run the translator (it wipes the C dir).
- For other programs, replace `cat` in the commands and in the paths.
- If `intercept-build` or `c2rust` aren’t found, re-check your PATH export above.

## Troubleshooting (from recent runs)
- Tests failing with `-v: command not found` or `sleep: missing operand`: set `AWK=awk` (defaulted in `run_c2r_tests.sh`).
- `getlimits: command not found` in head tests: ensure `$REPO_ROOT/c2saferrust/coreutils/getlimits` is on PATH; the runner’s default `PATH_PREFIX` now includes it.
- `num_traits::Float` unresolved for translated programs like `tail`: the translator now injects `num-traits = "0.2"` into generated Cargo.toml files; re-run the translator if you hit this.
- Numerous `unused label/parentheses` warnings from c2rust output are expected; focus on hard errors.

## Patched c2rust notes (tail fixes)
- Local patches to the c2rust transpiler widen integer and character literals to the caller’s expected integral type and align overflow builtins’ operand types, eliminating `i32`→`i64` mismatches (wip, but works).
- To use the patched tool:  
  ```sh
  CARGO_HOME="$REPO_ROOT/.cargo-local" \
  cargo +stable install --locked --force --git https://github.com/kings-crown/c2rust.git
  export PATH="$CARGO_HOME/bin:/usr/lib/llvm-15/bin:$PATH"

  
  CARGO_HOME=/home/brao/Desktop/.cargo-local \
  CARGO_TARGET_DIR=/tmp/c2rust-target \
  cargo +stable install --locked --force --path /home/brao/Desktop/c2rust/c2rust
  ```

  (Uses the kings-crown/c2rust fork that includes these fixes.)  
  Then rerun `create_c_and_rust_versions.py` as usual.
