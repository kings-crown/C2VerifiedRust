Compile-only regression snippets for c2rust-transpile
-----------------------------------------------------
Files:
  offt_minus.c      mixed-width subtraction stored in off_t
  shift_width.c     1<<31 vs 1L<<31 widening
  unsigned_sub.c    signed/unsigned subtraction underflow
  literal_narrow.c  large hex literal assigned to int
  varargs.c         varargs promotions with printf

How to run (from a c2rust checkout):
  CARGO_TARGET_DIR=/tmp/c2rust-target \
  cargo test -p c2rust-transpile --test compile_regress -- --nocapture

Place compile_regress.rs in c2rust-transpile/tests/ and the .c files in
c2rust-transpile/tests/compile_regress/ to enable the test target.
