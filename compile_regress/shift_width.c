#include <stddef.h>

long shift_no_suffix(void) {
    /* 1 is int; shifting by 31 should widen to long before assignment. */
    long x = 1 << 31;
    return x;
}

long shift_with_suffix(void) {
    /* Explicit long literal. */
    long x = 1L << 31;
    return x;
}
