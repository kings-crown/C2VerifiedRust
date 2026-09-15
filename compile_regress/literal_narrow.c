#include <stdint.h>

int narrow_hex(void) {
    /* Large hex literal that exactly fits in signed 32-bit. */
    int x = 0x80000000;
    return x;
}
