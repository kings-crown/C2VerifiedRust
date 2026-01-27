# C2VerifiedRust

## Regression snippets for c2rust-transpile

We keep a small compile-only regression suite under `compile_regress/` that mirrors the width/promotion bugs found while fixing `tail`:

- `offt_minus.c` – `off_t minus_n = 0 - n_bytes;`
- `shift_width.c` – `1 << 31` vs `1L << 31`
- `unsigned_sub.c` – signed/unsigned subtraction underflow
- `literal_narrow.c` – large hex literal assigned to `int`
- `varargs.c` – varargs promotions with `printf`

How to run (using the on-device `c2rust` checkout in `/home/brao/Desktop/c2rust`):
1. Copy the harness into the checkout:
   ```
   cp c2rust-transpile/tests/compile_regress.rs /home/brao/Desktop/c2rust/c2rust-transpile/tests/
   ```
2. Copy the snippets:
   ```
   mkdir -p /home/brao/Desktop/c2rust/c2rust-transpile/tests/compile_regress
   cp compile_regress/*.c /home/brao/Desktop/c2rust/c2rust-transpile/tests/compile_regress/
   ```
3. Run the test:
   ```
   CARGO_TARGET_DIR=/tmp/c2rust-target \
   PATH="/usr/lib/llvm-15/bin:$PATH" \
   cargo test \
     --manifest-path /home/brao/Desktop/c2rust/Cargo.toml \
     -p c2rust-transpile \
     --test compile_regress \
     -- --nocapture
   ```
4. (Optional) Clean up the staged copies from the `c2rust` checkout afterward to keep that tree clean.

These steps transpile each snippet and compile the generated Rust, catching type/promotion regressions. The canonical copies live here in `compile_regress/` (C files) and `c2rust-transpile/tests/compile_regress.rs` (harness).
