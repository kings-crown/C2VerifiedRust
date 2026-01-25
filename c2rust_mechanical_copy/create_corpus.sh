PROGRAMS_TO_TRANSLATE=(
    "sleep"
    "yes"
    "uniq"
    "dirname"
    "rmdir"
    "users"
    "kill"
    "wc"
    "printf"
    "cut"
    "head"
    "touch"
    "true"
    "date"
    "truncate"
    "cp"
    "paste"
    "split"
    "cat"
    "who"
    "tail"
    "pwd"
    "join"
    "factor"
    "false"
    "whoami"
    "echo"
    "sort"
)

# Set these to your environment or export before running.
OUT_DIR=${CORPUS_DIR:-/tmp/c2rust_corpus/coreutils}
COREUTILS_DIR=${COREUTILS_SRC:-/tmp/coreutils}

mkdir -p "$OUT_DIR"

for prog in "${PROGRAMS_TO_TRANSLATE[@]}"; do
    echo "Working on '$prog' in the background..."
    python3 create_c_and_rust_versions.py \
        --program_name "$prog" \
        --coreutils_dir "$COREUTILS_DIR" \
        --corpus_dir "$OUT_DIR" \
        > "$OUT_DIR"/"$prog".log 2>&1
done
