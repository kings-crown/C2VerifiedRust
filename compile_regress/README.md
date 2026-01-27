## Testing patched vs. stock `c2rust`

### 1) Select the `c2rust` binary

- **Patched (local tree):**
  ```bash
  cd /home/brao/Desktop/c2rust
  cargo build -p c2rust-transpile
  cargo install --locked --force --path c2rust
  c2rust --version    # expect 0.21.0-patched.1
  export PATH="/home/brao/Desktop/c2rust/target/debug:$HOME/.cargo/bin:/usr/lib/llvm-15/bin:$PATH"
  ```

- **Stock (crates.io):**
  ```bash
  cargo install --locked c2rust
  export PATH="$HOME/.cargo/bin:/usr/lib/llvm-15/bin:$PATH"
  c2rust --version                    # expect 0.21.0
  ```

Switching PATH between these lets you compare behaviors.

### 2) Transpile the regression snippets

From `/home/brao/Desktop/C2VerifiedRust`:

```bash
python3 - <<'PY' >/tmp/compile_commands.json
import json
base="/home/brao/Desktop/C2VerifiedRust"
files=[
  "compile_regress/offt_minus.c",
  "compile_regress/shift_width.c",
  "compile_regress/unsigned_sub.c",
  "compile_regress/literal_narrow.c",
  "compile_regress/varargs.c",
]
json.dump([{
  "directory": base,
  "command": f"clang -c -o /dev/null -w {base}/{c}",
  "file": f"{base}/{c}",
} for c in files], open("/tmp/compile_commands.json","w"))
PY

c2rust-transpile --overwrite-existing /tmp/compile_commands.json
```

This regenerates the `.rs` files in `compile_regress/` using the `c2rust-transpile` on PATH.

### 3) Compile the generated Rust

Still in `/home/brao/Desktop/C2VerifiedRust`:

```bash
sysroot=$(rustc --print sysroot)
for f in compile_regress/*.rs; do
  stem=${f%.rs}; stem=${stem##*/}
  rustc --sysroot "$sysroot" --edition 2021 \
        --crate-type lib --crate-name "$stem" \
        -o "/tmp/lib${stem}.rlib" \
        "$f"
done
```

No errors here means the transpiled snippets build. Run with patched PATH, then with stock PATH to compare. Please be mindful of the PATH that gets picked up.

### 4) End-to-end `tail` pipeline (optional)

Using whichever binary is on PATH:

```bash
cd /home/brao/Desktop/C2VerifiedRust/c2rust_baseline
python3 create_c_and_rust_versions.py \
  --program_name tail \
  --coreutils_dir "$COREUTILS_SRC" \
  --corpus_dir "$CORPUS_DIR"

./run_c2r_tests.sh tail
```

This rebuilds C and Rust for `tail` and runs the curated test subset; use patched vs. stock PATH to see the difference.
