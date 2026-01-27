#include <stddef.h>

unsigned subtract_underflow(void) {
    /* Mixed signed/unsigned subtraction should produce an unsigned result. */
    unsigned u = 0 - 1;
    return u;
}

