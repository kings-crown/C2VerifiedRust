#include <sys/types.h>
#include <stddef.h>

/* Regression: mixed-width subtraction feeding into a wider destination. */
off_t demo(off_t n_bytes) {
    /* Intentional: usual arithmetic conversions should not narrow the result. */
    off_t minus_n = 0 - n_bytes;
    return minus_n;
}
